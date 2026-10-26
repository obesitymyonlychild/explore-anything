import uuid

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id
from app.llm import errors
from app.llm.light import LightLLM, LightLLMError, get_light_llm
from app.schemas import SparkOut
from app.services import budget
from app.services import spark as spark_service

router = APIRouter(tags=["spark"])


@router.post("/spark", response_model=SparkOut)
async def spark(
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
    llm: LightLLM = Depends(get_light_llm),
):
    """Pick a random concept to explore. The client then starts a thread with action=spark."""
    await budget.ensure_within_budget(session, user_id)
    try:
        return await spark_service.spark(session, user_id, llm)
    except anthropic.APIError as e:
        code, message = errors.describe(e)
        if code in ("auth", "out_of_credit"):
            raise HTTPException(502, message) from e
        raise HTTPException(502, "Couldn't pick a concept right now. Try again.") from e
    except LightLLMError as e:
        budget.record(session, user_id, "spark", e.model, e.usage)  # billed even though unusable
        await session.commit()
        raise HTTPException(502, "Couldn't pick a concept right now. Try again.") from e
    except (KeyError, ValueError) as e:
        raise HTTPException(502, "Couldn't pick a concept right now. Try again.") from e
