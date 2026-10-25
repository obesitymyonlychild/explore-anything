import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base
from app.settings import DEFAULT_USER_ID


def current_user_id() -> uuid.UUID:
    # Single-user MVP. Replaced by real auth in P4.
    return DEFAULT_USER_ID


async def get_owned[M: Base](session: AsyncSession, model: type[M], obj_id: uuid.UUID, user_id: uuid.UUID) -> M:
    """Load a row that belongs to the user, or 404."""
    obj = await session.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", None) != user_id:
        raise HTTPException(status_code=404, detail=f"{model.__tablename__} not found")
    return obj
