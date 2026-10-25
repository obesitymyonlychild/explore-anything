import re
import unicodedata
import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Concept


def slugify(name: str) -> str:
    """Dedupe key: "Vapor-Compression  Cycle!" -> "vapor-compression-cycle". Keeps + and # (C++ != C)."""
    s = unicodedata.normalize("NFKC", name).casefold()
    s = re.sub(r"[^\w+#]+", "-", s)
    return s.strip("-_")


def clean_name(name: str) -> str:
    return " ".join(name.split())


async def get_or_create(session: AsyncSession, user_id: uuid.UUID, name: str, *, explored: bool = False) -> Concept:
    """Find a concept by slug or create it. `explored=True` marks it as having a card."""
    name = clean_name(name)
    slug = slugify(name)
    if not slug:
        raise ValueError("concept name has no usable characters")

    await session.execute(
        insert(Concept)
        .values(user_id=user_id, name=name, slug=slug, explored=explored)
        .on_conflict_do_nothing(index_elements=["user_id", "slug"])
    )
    if explored:
        await session.execute(
            update(Concept)
            .where(Concept.user_id == user_id, Concept.slug == slug, Concept.explored.is_(False))
            .values(explored=True)
        )
    return await session.scalar(
        select(Concept)
        .where(Concept.user_id == user_id, Concept.slug == slug)
        .execution_options(populate_existing=True)
    )
