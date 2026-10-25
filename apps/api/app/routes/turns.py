import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id, get_owned
from app.llm.client import CardLLM, get_llm
from app.llm.light import LightLLM, get_light_llm
from app.models import Thread
from app.schemas import TurnRequest
from app.services.orchestrator import prepare_turn, run_turn

router = APIRouter(tags=["turns"])


@router.post("/threads/{thread_id}/turns")
async def create_turn(
    thread_id: uuid.UUID,
    req: TurnRequest,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
    llm: CardLLM = Depends(get_llm),
    light_llm: LightLLM = Depends(get_light_llm),
):
    """Stream one hook card as server-sent events: meta → status → card (repeated) → done | error,
    then `title` after a thread's first card."""
    thread = await get_owned(session, Thread, thread_id, user_id)
    turn = await prepare_turn(session, user_id, thread, req)
    return StreamingResponse(
        run_turn(turn, llm, light_llm),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
