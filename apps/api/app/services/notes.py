import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.prompt import Notes
from app.models import Concept, ConceptLink, Takeaway, takeaway_concept

MAX_ITEMS = 20  # per kind, newest first


async def load_notes(session: AsyncSession, user_id: uuid.UUID, concept: Concept) -> Notes:
    links = await session.scalars(
        select(ConceptLink)
        .where(
            ConceptLink.user_id == user_id,
            or_(ConceptLink.a_concept_id == concept.id, ConceptLink.b_concept_id == concept.id),
        )
        .order_by(ConceptLink.created_at.desc())
        .limit(MAX_ITEMS)
    )
    takeaways = await session.scalars(
        select(Takeaway)
        .join(takeaway_concept, takeaway_concept.c.takeaway_id == Takeaway.id)
        .where(Takeaway.user_id == user_id, takeaway_concept.c.concept_id == concept.id)
        .order_by(Takeaway.created_at.desc())
        .limit(MAX_ITEMS)
    )
    return Notes(
        concept=concept.name,
        links=[((link.b if link.a_concept_id == concept.id else link.a).name, link.note) for link in links.unique()],
        takeaways=[(t.kind, t.body) for t in takeaways],
    )
