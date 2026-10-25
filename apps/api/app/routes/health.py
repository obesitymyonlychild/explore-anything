from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    try:
        await session.execute(text("select 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"db": db_ok, "anthropic_api_key": bool(get_settings().anthropic_api_key)}
