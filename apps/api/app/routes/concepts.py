import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id, get_owned
from app.models import Concept, ConceptLink, Message, Takeaway, Thread, takeaway_concept
from app.schemas import ConceptCreate, ConceptDetail, ConceptOut, ConceptRef, LinkedConcept
from app.services import concepts as concept_service

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get("", response_model=list[ConceptOut])
async def list_concepts(
    q: str = "",
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    """All concepts alphabetically, or, with `q`, autocomplete matches (prefix matches first)."""
    stmt = select(Concept).where(Concept.user_id == user_id)
    q = q.strip()
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Concept.name.ilike(f"%{escaped}%")).order_by(
            case((Concept.name.ilike(f"{escaped}%"), 0), else_=1), Concept.name
        )
    else:
        stmt = stmt.order_by(Concept.name)
    return (await session.scalars(stmt.limit(limit))).all()


@router.post("", response_model=ConceptOut)
async def create_concept(
    body: ConceptCreate,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    """Get-or-create by name (case/punctuation-insensitive)."""
    try:
        concept = await concept_service.get_or_create(session, user_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await session.commit()
    return concept


@router.get("/{concept_id}", response_model=ConceptDetail)
async def get_concept(
    concept_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    concept = await get_owned(session, Concept, concept_id, user_id)

    cards = await session.scalars(
        select(Message)
        .join(Thread, Thread.id == Message.thread_id)
        .where(Thread.user_id == user_id, Message.role == "assistant", Message.concept_id == concept_id)
        .order_by(Message.created_at)
    )

    link_rows = await session.scalars(
        select(ConceptLink)
        .where(
            ConceptLink.user_id == user_id,
            or_(ConceptLink.a_concept_id == concept_id, ConceptLink.b_concept_id == concept_id),
        )
        .order_by(ConceptLink.created_at.desc())
    )
    links = [
        LinkedConcept(
            link_id=link.id,
            concept=ConceptRef.model_validate(link.b if link.a_concept_id == concept_id else link.a),
            note=link.note,
            created_by=link.created_by,
            created_at=link.created_at,
        )
        for link in link_rows.unique()
    ]

    takeaways = await session.scalars(
        select(Takeaway)
        .join(takeaway_concept, takeaway_concept.c.takeaway_id == Takeaway.id)
        .where(Takeaway.user_id == user_id, takeaway_concept.c.concept_id == concept_id)
        .order_by(Takeaway.created_at.desc())
    )

    return ConceptDetail(concept=concept, cards=cards.all(), links=links, takeaways=takeaways.all())
