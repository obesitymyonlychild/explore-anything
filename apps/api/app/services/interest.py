import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InterestEvent


def record(
    session: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    *,
    thread_id: uuid.UUID | None = None,
    concept_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Add an interest event to the session; committed with the caller's transaction."""
    session.add(InterestEvent(user_id=user_id, action=action, thread_id=thread_id, concept_id=concept_id, meta=meta))
