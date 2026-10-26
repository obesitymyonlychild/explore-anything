import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user_id
from app.schemas import UsageOut
from app.services import budget

router = APIRouter(tags=["usage"])


@router.get("/usage", response_model=UsageOut)
async def usage(session: AsyncSession = Depends(get_session), user_id: uuid.UUID = Depends(current_user_id)):
    """Spend today and this month against the budgets in .env."""
    s = await budget.spend(session, user_id)
    return UsageOut(
        today_usd=round(s.today_usd, 4),
        month_usd=round(s.month_usd, 4),
        daily_budget_usd=s.daily_budget_usd,
        monthly_budget_usd=s.monthly_budget_usd,
        warn=s.warn,
        blocked=s.blocked,
        reason=s.reason(),
        month_by_purpose=s.month_by_purpose,
    )
