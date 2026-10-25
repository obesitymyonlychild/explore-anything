import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id, get_owned
from app.models import Concept, Message, Takeaway, Thread, takeaway_concept
from app.schemas import TakeawayCreate, TakeawayKind, TakeawayOut, TakeawayUpdate
from app.services import interest

router = APIRouter(prefix="/takeaways", tags=["takeaways"])


async def load_concepts(session: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Concept]:
    unique_ids = list(dict.fromkeys(ids))
    found = (await session.scalars(select(Concept).where(Concept.user_id == user_id, Concept.id.in_(unique_ids)))).all()
    if len(found) != len(unique_ids):
        raise HTTPException(status_code=404, detail="concept not found")
    by_id = {c.id: c for c in found}
    return [by_id[i] for i in unique_ids]


@router.get("", response_model=list[TakeawayOut])
async def list_takeaways(
    concept_id: uuid.UUID | None = None,
    kind: TakeawayKind | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    stmt = select(Takeaway).where(Takeaway.user_id == user_id)
    if concept_id:
        stmt = stmt.join(takeaway_concept, takeaway_concept.c.takeaway_id == Takeaway.id).where(
            takeaway_concept.c.concept_id == concept_id
        )
    if kind:
        stmt = stmt.where(Takeaway.kind == kind)
    return (await session.scalars(stmt.order_by(Takeaway.created_at.desc()))).all()


@router.post("", response_model=TakeawayOut, status_code=201)
async def create_takeaway(
    body: TakeawayCreate,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    concepts = await load_concepts(session, user_id, body.concept_ids)

    thread_id = None
    if body.message_id:
        thread_id = await session.scalar(
            select(Message.thread_id)
            .join(Thread, Thread.id == Message.thread_id)
            .where(Message.id == body.message_id, Thread.user_id == user_id)
        )
        if thread_id is None:
            raise HTTPException(status_code=404, detail="message not found")

    takeaway = Takeaway(
        user_id=user_id,
        kind=body.kind,
        body=body.body.strip(),
        message_id=body.message_id,
        thread_id=thread_id,
        concepts=concepts,
    )
    session.add(takeaway)
    interest.record(
        session,
        user_id,
        "takeaway",
        thread_id=thread_id,
        concept_id=concepts[0].id,
        meta={"kind": body.kind, "concept_ids": [str(c.id) for c in concepts]},
    )
    await session.commit()
    await session.refresh(takeaway)
    return takeaway


@router.patch("/{takeaway_id}", response_model=TakeawayOut)
async def update_takeaway(
    takeaway_id: uuid.UUID,
    body: TakeawayUpdate,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    takeaway = await get_owned(session, Takeaway, takeaway_id, user_id)
    if body.body is not None:
        takeaway.body = body.body.strip()
    if body.kind is not None:
        takeaway.kind = body.kind
    if body.concept_ids is not None:
        takeaway.concepts = await load_concepts(session, user_id, body.concept_ids)
    takeaway.updated_at = func.now()  # also bump when only the concept list changed
    await session.commit()
    await session.refresh(takeaway)
    return takeaway


@router.delete("/{takeaway_id}", status_code=204)
async def delete_takeaway(
    takeaway_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    takeaway = await get_owned(session, Takeaway, takeaway_id, user_id)
    await session.delete(takeaway)
    await session.commit()
    return Response(status_code=204)
