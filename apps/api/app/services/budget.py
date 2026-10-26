"""Cost ledger and spend limits.

Every API call is recorded in `api_call` with its cost. Before a turn or a Surprise me pick, the
app checks today's and this month's spend against DAILY_BUDGET_USD / MONTHLY_BUDGET_USD (0 = no
limit). Days and months follow the server's local time. A call already in flight is never cut off,
so one card can overshoot a limit by at most its own cost (max_tokens caps that at about $0.35).

The hard ceiling belongs in the Anthropic console (workspace spend limit); this layer makes
overspending unlikely and says clearly why a turn was refused.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.pricing import cost_usd
from app.models import BUDGETED_PURPOSES, ApiCall
from app.settings import get_settings

WARN_AT = 0.8  # share of a budget at which the page starts warning


def record(
    session: AsyncSession,
    user_id: uuid.UUID,
    purpose: str,
    model: str,
    usage: dict[str, Any],
    *,
    thread_id: uuid.UUID | None = None,
) -> ApiCall:
    """Add a ledger row to the session; committed with the caller's transaction."""
    created = usage.get("cache_creation") or {}
    write = sum(created.values()) if created else usage.get("cache_creation_input_tokens", 0)
    row = ApiCall(
        user_id=user_id,
        purpose=purpose,
        model=model,
        thread_id=thread_id,
        input_tokens=usage.get("input_tokens", 0) or 0,
        cache_write_tokens=write or 0,
        cache_read_tokens=usage.get("cache_read_input_tokens", 0) or 0,
        output_tokens=usage.get("output_tokens", 0) or 0,
        cost_usd=Decimal(str(round(cost_usd(model, usage), 6))),
        usage=usage,
    )
    session.add(row)
    return row


def period_starts(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Local midnight today and on the 1st of this month, as aware datetimes."""
    now = (now or datetime.now()).astimezone()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day, day.replace(day=1)


@dataclass
class Spend:
    today_usd: float
    month_usd: float
    daily_budget_usd: float
    monthly_budget_usd: float
    month_by_purpose: dict[str, float]

    def _share(self) -> float:
        shares = [
            spent / limit
            for spent, limit in ((self.today_usd, self.daily_budget_usd), (self.month_usd, self.monthly_budget_usd))
            if limit > 0
        ]
        return max(shares, default=0.0)

    @property
    def blocked(self) -> bool:
        return self._share() >= 1

    @property
    def warn(self) -> bool:
        return self._share() >= WARN_AT

    def reason(self) -> str | None:
        if self.daily_budget_usd > 0 and self.today_usd >= self.daily_budget_usd:
            return (
                f"Daily budget reached (${self.today_usd:.2f} of ${self.daily_budget_usd:.2f}). "
                "It resets at midnight, or raise DAILY_BUDGET_USD in .env."
            )
        if self.monthly_budget_usd > 0 and self.month_usd >= self.monthly_budget_usd:
            return (
                f"Monthly budget reached (${self.month_usd:.2f} of ${self.monthly_budget_usd:.2f}). "
                "Raise MONTHLY_BUDGET_USD in .env to continue."
            )
        return None


async def spend(session: AsyncSession, user_id: uuid.UUID) -> Spend:
    day, month = period_starts()
    s = get_settings()
    budgeted = ApiCall.purpose.in_(BUDGETED_PURPOSES)
    today = await session.scalar(
        select(func.coalesce(func.sum(ApiCall.cost_usd), 0)).where(
            ApiCall.user_id == user_id, budgeted, ApiCall.ts >= day
        )
    )
    by_purpose = dict(
        (
            await session.execute(
                select(ApiCall.purpose, func.sum(ApiCall.cost_usd))
                .where(ApiCall.user_id == user_id, ApiCall.ts >= month)
                .group_by(ApiCall.purpose)
            )
        ).all()
    )
    month_budgeted = sum(v for k, v in by_purpose.items() if k in BUDGETED_PURPOSES)
    return Spend(
        today_usd=float(today),
        month_usd=float(month_budgeted),
        daily_budget_usd=s.daily_budget_usd,
        monthly_budget_usd=s.monthly_budget_usd,
        month_by_purpose={k: round(float(v), 4) for k, v in by_purpose.items()},
    )


async def ensure_within_budget(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Raise HTTP 402 if a budget is used up. Call before starting any budgeted API work."""
    current = await spend(session, user_id)
    if current.blocked:
        raise HTTPException(status_code=402, detail=current.reason())
