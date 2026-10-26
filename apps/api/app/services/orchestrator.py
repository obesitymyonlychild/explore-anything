"""One exploration turn: store the user turn, stream a hook card, store the card.

The user turn is committed before streaming starts. If the stream fails, that user turn
is left without a reply and is replaced by the next turn (the retry), so history always
alternates user/assistant and earlier turns are never edited.
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anthropic
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.deps import get_owned
from app.llm import errors
from app.llm.client import CardLLM, Final, TextDelta, ThinkingStarted
from app.llm.light import LightLLM
from app.llm.partial import PartialJSON
from app.llm.prompt import Notes, system_blocks, user_turn
from app.models import DEPTHS, Concept, Message, Takeaway, Thread
from app.schemas import Card, TurnRequest
from app.services import budget, interest, titles
from app.services.concepts import get_or_create, slugify
from app.services.notes import load_notes

log = logging.getLogger(__name__)

EMIT_INTERVAL = 0.05  # seconds between partial-card events
MAX_HIGHLIGHTS = 3

DEFAULT_TEXT = {
    "dive": "Go deeper.",
    "switch": "Show me something completely different.",
    "spark": "Surprise me.",
}


@dataclass
class PreparedTurn:
    thread_id: uuid.UUID
    user_id: uuid.UUID
    user_message_id: uuid.UUID
    depth: str
    system: list[dict[str, Any]]
    history: list[dict[str, Any]]
    first_turn: bool = False  # the thread's first card: generate a title after it
    first_message: str = ""


def next_depth(depth: str) -> str:
    return DEPTHS[min(DEPTHS.index(depth) + 1, len(DEPTHS) - 1)]


async def find_concept(session: AsyncSession, user_id: uuid.UUID, name: str) -> Concept | None:
    return await session.scalar(select(Concept).where(Concept.user_id == user_id, Concept.slug == slugify(name)))


async def prepare_turn(session: AsyncSession, user_id: uuid.UUID, thread: Thread, req: TurnRequest) -> PreparedTurn:
    text = (req.text or "").strip()
    target = (req.concept or "").strip()
    current = await session.get(Concept, thread.current_concept_id) if thread.current_concept_id else None

    takeaway = None
    if req.takeaway_id:
        if req.action != "ask":
            raise HTTPException(422, "takeaway_id only works with action=ask")
        takeaway = await get_owned(session, Takeaway, req.takeaway_id, user_id)
        text = text or takeaway.body
    if req.action == "ask" and not text:
        raise HTTPException(422, "text is required for action=ask")
    if req.action in ("branch", "spark") and not target:
        raise HTTPException(422, f"concept is required for action={req.action}")
    if req.action == "dive" and current is None:
        raise HTTPException(422, "nothing to go deeper on yet")

    depth = req.depth or (next_depth(thread.depth) if req.action == "dive" else thread.depth)

    # The concept this turn is about, if known up front (its notes go into the prompt).
    focus: Concept | None
    if req.action in ("branch", "spark"):
        focus = await find_concept(session, user_id, target)  # may not exist yet; the card creates it
    elif takeaway and takeaway.concepts:
        focus = takeaway.concepts[0]
    elif req.action == "switch":
        focus = None
    else:
        focus = current
    focus_name = target or (focus.name if focus else None)
    if req.action == "switch":
        focus_name = None

    notes: Notes | None = await load_notes(session, user_id, focus) if focus else None
    display = text or DEFAULT_TEXT.get(req.action) or f"Tell me about {target}."
    composed = user_turn(req.action, depth, focus_name, display, notes)

    # A trailing user turn has no reply (its stream failed): this turn replaces it.
    last = await session.scalar(select(Message).where(Message.thread_id == thread.id).order_by(Message.seq.desc()))
    if last is not None and last.role == "user":
        await session.execute(delete(Message).where(Message.id == last.id))
        last_seq = last.seq - 1
    else:
        last_seq = last.seq if last else 0

    label = {"branch": f"Related: {target}", "spark": f"Surprise me: {target}"}.get(req.action, display)
    user_msg = Message(
        thread_id=thread.id,
        seq=last_seq + 1,
        role="user",
        action=req.action,
        content=text or label,
        api_content=[{"type": "text", "text": composed}],
    )
    session.add(user_msg)
    interest.record(
        session,
        user_id,
        "spark_shown" if req.action == "spark" else req.action,
        thread_id=thread.id,
        concept_id=focus.id if focus else None,
        meta={
            "depth": depth,
            **({"concept": target} if target else {}),
            **({"topic_area": req.topic_area} if req.action == "spark" and req.topic_area else {}),
        },
    )
    thread.depth = depth
    thread.last_active_at = func.now()
    await session.commit()

    messages = await session.scalars(select(Message).where(Message.thread_id == thread.id).order_by(Message.seq))
    history = [{"role": m.role, "content": m.api_content or [{"type": "text", "text": m.content}]} for m in messages]
    return PreparedTurn(
        thread.id,
        user_id,
        user_msg.id,
        depth,
        system_blocks(),
        history,
        first_turn=thread.root_concept_id is None,
        first_message=user_msg.content,
    )


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def error(code: str, message: str) -> str:
    return sse("error", {"code": code, "message": message})


async def run_turn(turn: PreparedTurn, llm: CardLLM, light_llm: LightLLM | None = None) -> AsyncIterator[str]:
    try:
        async for chunk in _run_turn(turn, llm, light_llm):
            yield chunk
    except Exception:
        # Anything unexpected still ends the stream with an error event the page can show.
        log.exception("turn failed")
        yield error("internal", "Something went wrong on the server. Try again.")


async def _run_turn(turn: PreparedTurn, llm: CardLLM, light_llm: LightLLM | None) -> AsyncIterator[str]:
    yield sse("meta", {"user_message_id": str(turn.user_message_id), "depth": turn.depth})

    parser = PartialJSON()
    final: Final | None = None
    last_emit, last_card = 0.0, None
    try:
        async for event in llm.stream_card(turn.system, turn.history):
            if isinstance(event, TextDelta):
                parser.feed(event.text)
                now = time.monotonic()
                if now - last_emit >= EMIT_INTERVAL:
                    card = parser.parse()
                    if card and card != last_card:
                        yield sse("card", card)
                        last_emit, last_card = now, card
            elif isinstance(event, ThinkingStarted):
                yield sse("status", {"state": "thinking"})
            else:
                final = event
    except anthropic.APIError as e:
        yield error(*errors.describe(e))
        return

    if final is None:
        yield error("api_error", "The stream ended without a final message.")
        return
    # Billed whether or not the card turns out usable, so record it before any other check.
    async with SessionLocal() as session:
        budget.record(session, turn.user_id, "turn", final.model, final.usage, thread_id=turn.thread_id)
        await session.commit()

    if final.stop_reason == "refusal":
        yield error("refusal", "Claude declined this one. Try rephrasing, or pick another branch.")
        return
    if final.stop_reason == "max_tokens":
        yield error("max_tokens", "The card got cut off (output limit). Try again or lower the depth.")
        return

    try:
        card = Card.model_validate_json(parser.text)
    except ValidationError:
        yield error("invalid_card", "Claude's reply wasn't a valid card. Try again.")
        return
    card.depth = turn.depth
    card.highlights = card.highlights[:MAX_HIGHLIGHTS]
    card_data = card.model_dump()

    async with SessionLocal() as session:
        concept = await get_or_create(session, turn.user_id, card.concept, explored=True)
        thread = await session.get(Thread, turn.thread_id)
        last_seq = await session.scalar(select(func.max(Message.seq)).where(Message.thread_id == turn.thread_id))
        msg = Message(
            thread_id=turn.thread_id,
            seq=(last_seq or 0) + 1,
            role="assistant",
            content=json.dumps(card_data, ensure_ascii=False),
            card=card_data,
            api_content=final.content,
            concept_id=concept.id,
            model=final.model,
            usage=final.usage,
        )
        session.add(msg)
        thread.current_concept_id = concept.id
        thread.root_concept_id = thread.root_concept_id or concept.id
        thread.title = thread.title or concept.name  # provisional; generated titles arrive in M5
        thread.last_active_at = func.now()
        await session.commit()

    yield sse(
        "done",
        {"card": card_data, "message_id": str(msg.id), "concept_id": str(concept.id), "usage": final.usage},
    )

    if turn.first_turn and light_llm is not None:
        title, result = await titles.generate_title(light_llm, turn.first_message, card)
        if result is not None:
            async with SessionLocal() as session:
                budget.record(session, turn.user_id, "title", result.model, result.usage, thread_id=turn.thread_id)
                if title:
                    thread = await session.get(Thread, turn.thread_id)
                    thread.title = title
                await session.commit()
        if title:
            yield sse("title", {"title": title})
