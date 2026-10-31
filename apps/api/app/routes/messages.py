import uuid

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id
from app.llm import errors
from app.llm.light import LightLLM, LightLLMError, get_light_llm
from app.models import InterestEvent, Message, Thread
from app.schemas import FavouriteOut
from app.services import budget, interest, translate

router = APIRouter(prefix="/messages", tags=["messages"])


class TranslationOut(BaseModel):
    message_id: uuid.UUID
    zh: dict


async def owned_card(session: AsyncSession, message_id: uuid.UUID, user_id: uuid.UUID) -> Message:
    msg = await session.scalar(
        select(Message)
        .join(Thread, Thread.id == Message.thread_id)
        .where(Message.id == message_id, Thread.user_id == user_id)
    )
    if msg is None or msg.role != "assistant" or not msg.card:
        raise HTTPException(404, "card not found")
    return msg


@router.get("/favourites", response_model=list[FavouriteOut])
async def list_favourites(
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    # Only the columns the list shows: whole rows would drag in card and api_content JSONB.
    rows = await session.execute(
        select(
            Message.id.label("message_id"),
            Message.thread_id,
            Thread.title.label("thread_title"),
            Message.card["concept"].astext.label("concept"),
            Message.card["one_liner"].astext.label("one_liner"),
            Message.favourited_at,
        )
        .join(Thread, Thread.id == Message.thread_id)
        .where(Thread.user_id == user_id, Message.favourited_at.is_not(None))
        .order_by(Message.favourited_at.desc())
    )
    return [FavouriteOut(**row._mapping) for row in rows]


@router.put("/{message_id}/favourite", status_code=204)
async def add_favourite(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    msg = await owned_card(session, message_id, user_id)
    if msg.favourited_at is None:  # idempotent: keeps its place in the list
        msg.favourited_at = func.now()
        # One interest event per card, however often it's toggled off and on again.
        already = await session.scalar(
            select(InterestEvent.id).where(
                InterestEvent.user_id == user_id,
                InterestEvent.action == "favourite",
                InterestEvent.meta["message_id"].astext == str(msg.id),
            )
        )
        if already is None:
            interest.record(
                session, user_id, "favourite",
                thread_id=msg.thread_id, concept_id=msg.concept_id, meta={"message_id": str(msg.id)},
            )
    await session.commit()
    return Response(status_code=204)


@router.delete("/{message_id}/favourite", status_code=204)
async def remove_favourite(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    msg = await owned_card(session, message_id, user_id)
    msg.favourited_at = None
    await session.commit()
    return Response(status_code=204)


@router.post("/{message_id}/translate", response_model=TranslationOut)
async def translate_message(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
    llm: LightLLM = Depends(get_light_llm),
):
    """Chinese for a card that doesn't have it yet (cards made before translation existed, or after a
    failed translation). Returns the stored translation without a new call if there is one."""
    msg = await owned_card(session, message_id, user_id)
    if msg.card.get("zh"):
        return TranslationOut(message_id=msg.id, zh=msg.card["zh"])

    await budget.ensure_within_budget(session, user_id)
    try:
        zh, result = await translate.translate_card(llm, msg.card)
    except LightLLMError as e:
        budget.record(session, user_id, "translate", e.model, e.usage, thread_id=msg.thread_id)
        await session.commit()
        raise HTTPException(502, "The translation didn't come through. Try again.") from e
    except anthropic.APIError as e:
        raise HTTPException(502, errors.describe(e)[1]) from e
    budget.record(session, user_id, "translate", result.model, result.usage, thread_id=msg.thread_id)
    msg.card = {**msg.card, "zh": zh}
    await session.commit()
    return TranslationOut(message_id=msg.id, zh=zh)
