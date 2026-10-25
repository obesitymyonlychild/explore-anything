import uuid

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id
from app.llm.light import LightLLM, LightLLMError, get_light_llm
from app.schemas import SparkOut
from app.services import spark as spark_service

router = APIRouter(tags=["spark"])


@router.post("/spark", response_model=SparkOut)
async def spark(
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
    llm: LightLLM = Depends(get_light_llm),
):
    """Pick a random concept to explore. The client then starts a thread with action=spark."""
    try:
        return await spark_service.spark(session, user_id, llm)
    except anthropic.AuthenticationError as e:
        raise HTTPException(502, "Anthropic API key missing or invalid. Check ANTHROPIC_API_KEY in .env.") from e
    except (anthropic.APIError, LightLLMError, KeyError, ValueError) as e:
        raise HTTPException(502, "Couldn't pick a concept right now. Try again.") from e
