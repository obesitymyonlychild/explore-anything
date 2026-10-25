import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id, get_owned
from app.models import Concept, ConceptLink
from app.schemas import ConceptRef, LinkCreate, LinkOut, LinkUpdate
from app.services import interest

router = APIRouter(prefix="/links", tags=["links"])


def to_out(link: ConceptLink) -> LinkOut:
    return LinkOut(
        id=link.id,
        a=ConceptRef.model_validate(link.a),
        b=ConceptRef.model_validate(link.b),
        note=link.note,
        created_by=link.created_by,
        created_at=link.created_at,
    )


@router.post("", response_model=LinkOut, status_code=201)
async def create_link(
    body: LinkCreate,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    if body.a_concept_id == body.b_concept_id:
        raise HTTPException(status_code=422, detail="a concept can't be linked to itself")
    a = await get_owned(session, Concept, body.a_concept_id, user_id)
    b = await get_owned(session, Concept, body.b_concept_id, user_id)
    if a.id > b.id:  # undirected: store each pair once, smaller id first
        a, b = b, a

    existing = await session.scalar(
        select(ConceptLink).where(ConceptLink.a_concept_id == a.id, ConceptLink.b_concept_id == b.id)
    )
    if existing:
        raise HTTPException(status_code=409, detail={"message": "link already exists", "link_id": str(existing.id)})

    link = ConceptLink(user_id=user_id, a=a, b=b, note=body.note.strip())
    session.add(link)
    interest.record(
        session, user_id, "link", concept_id=body.a_concept_id, meta={"other_concept_id": str(body.b_concept_id)}
    )
    await session.commit()
    await session.refresh(link)
    return to_out(link)


@router.patch("/{link_id}", response_model=LinkOut)
async def update_link(
    link_id: uuid.UUID,
    body: LinkUpdate,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    link = await get_owned(session, ConceptLink, link_id, user_id)
    link.note = body.note.strip()
    await session.commit()
    return to_out(link)


@router.delete("/{link_id}", status_code=204)
async def delete_link(
    link_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    link = await get_owned(session, ConceptLink, link_id, user_id)
    await session.delete(link)
    await session.commit()
    return Response(status_code=204)
