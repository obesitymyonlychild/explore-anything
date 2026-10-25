import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.deps import current_user_id, get_owned
from app.models import Thread
from app.schemas import ThreadCreate, ThreadDetail, ThreadOut, ThreadUpdate
from app.services import interest

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("", response_model=list[ThreadOut])
async def list_threads(
    archived: bool = False,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    rows = await session.scalars(
        select(Thread)
        .where(Thread.user_id == user_id, Thread.archived.is_(archived))
        .order_by(Thread.last_active_at.desc())
    )
    return rows.all()


@router.post("", response_model=ThreadOut, status_code=201)
async def create_thread(
    body: ThreadCreate,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    # Turns (and the thread's concept) arrive via POST /threads/{id}/turns in M2.
    thread = Thread(user_id=user_id, title=body.title)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


@router.get("/{thread_id}", response_model=ThreadDetail)
async def get_thread(
    thread_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    await get_owned(session, Thread, thread_id, user_id)
    return await session.scalar(select(Thread).where(Thread.id == thread_id).options(selectinload(Thread.messages)))


@router.patch("/{thread_id}", response_model=ThreadOut)
async def update_thread(
    thread_id: uuid.UUID,
    body: ThreadUpdate,
    session: AsyncSession = Depends(get_session),
    user_id: uuid.UUID = Depends(current_user_id),
):
    thread = await get_owned(session, Thread, thread_id, user_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "depth" in changes and changes["depth"] != thread.depth:
        interest.record(
            session,
            user_id,
            "depth_set",
            thread_id=thread.id,
            concept_id=thread.current_concept_id,
            meta={"from": thread.depth, "to": changes["depth"]},
        )
    for field, value in changes.items():
        setattr(thread, field, value)
    await session.commit()
    await session.refresh(thread)
    return thread
