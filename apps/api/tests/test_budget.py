from datetime import datetime, timedelta
from decimal import Decimal

import anthropic
import httpx2
import pytest
from sqlalchemy import select

from app.llm import errors
from app.llm.light import get_light_llm
from app.llm.pricing import FALLBACK_PRICE, cost_usd
from app.main import app
from app.models import ApiCall
from app.services import budget
from app.settings import DEFAULT_USER_ID, get_settings
from tests.fake_llm import FakeLightLLM, Script, card
from tests.test_turns import new_thread, turn

# --- pricing -----------------------------------------------------------------


def test_cost_of_a_cached_opus_turn():
    usage = {
        "input_tokens": 4,
        "cache_read_input_tokens": 2440,
        "cache_creation_input_tokens": 873,
        "cache_creation": {"ephemeral_5m_input_tokens": 873, "ephemeral_1h_input_tokens": 0},
        "output_tokens": 2987,
    }
    expected = (4 * 4 + 2440 * 0.20 + 873 * 4 * 1.25 + 2987 * 20) / 1e6
    assert cost_usd("claude-opus-5-5", usage) == pytest.approx(expected)


def test_one_hour_cache_writes_cost_double():
    usage = {"cache_creation": {"ephemeral_1h_input_tokens": 1_000_000, "ephemeral_5m_input_tokens": 0}}
    assert cost_usd("claude-opus-5-5", usage) == pytest.approx(8.0)


def test_fallback_iterations_are_priced_per_attempt():
    usage = {
        "output_tokens": 999_999,  # top-level covers only the last attempt; iterations are the truth
        "iterations": [
            {"type": "message", "input_tokens": 1_000_000, "output_tokens": 0},
            {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 1_000_000, "output_tokens": 0},
        ],
    }
    assert cost_usd("claude-opus-5-5", usage) == pytest.approx(4.0 + 5.0)


def test_unknown_model_is_priced_conservatively():
    assert cost_usd("claude-new-9", {"output_tokens": 1_000_000}) == pytest.approx(FALLBACK_PRICE.output)


def test_haiku_long_prompt_tier():
    assert cost_usd("claude-haiku-5-5", {"input_tokens": 50_000}) == pytest.approx(0.005)
    assert cost_usd("claude-haiku-5-5", {"input_tokens": 200_000}) == pytest.approx(0.1)


# --- errors ------------------------------------------------------------------


def status_error(cls, status, message):
    return cls(message, response=httpx2.Response(status, request=httpx2.Request("POST", "https://x")), body=None)


def test_out_of_credit_is_recognised():
    e = status_error(anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API.")
    code, message = errors.describe(e)
    assert code == "out_of_credit" and "console.anthropic.com" in message
    assert errors.describe(status_error(anthropic.BadRequestError, 400, "bad schema"))[0] == "api_error"


# --- ledger & budgets --------------------------------------------------------


async def add_spend(session, usd, purpose="turn", ts=None):
    session.add(
        ApiCall(
            user_id=DEFAULT_USER_ID,
            purpose=purpose,
            model="claude-opus-5-5",
            cost_usd=Decimal(str(usd)),
            **({"ts": ts} if ts else {}),
        )
    )
    await session.commit()


@pytest.fixture
def budgets(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "daily_budget_usd", 1.0)
    monkeypatch.setattr(s, "monthly_budget_usd", 10.0)


async def test_turn_and_title_are_recorded(client, session, llm):
    llm.scripts.append(Script.of(card()))
    tid = await new_thread(client)
    await turn(client, tid, action="ask", text="air conditioning")
    rows = (await session.scalars(select(ApiCall).order_by(ApiCall.id))).all()
    assert sorted((r.purpose, r.model) for r in rows) == [
        ("title", "claude-haiku-5-5"),
        ("translate", "claude-haiku-5-5"),
        ("turn", "claude-opus-5-5"),
    ]
    assert str(rows[0].thread_id) == tid
    assert rows[0].cost_usd == Decimal(
        str(round(cost_usd("claude-opus-5-5", {"input_tokens": 100, "output_tokens": 50}), 6))
    )


async def test_refused_turns_are_still_recorded(client, session, llm):
    llm.scripts.append(Script("", stop_reason="refusal"))
    tid = await new_thread(client)
    await turn(client, tid, action="ask", text="hi")
    assert [r.purpose for r in (await session.scalars(select(ApiCall))).all()] == ["turn"]


async def test_usage_endpoint_and_warning(client, session, budgets):
    await add_spend(session, 0.85)
    await add_spend(session, 3.0, purpose="eval")  # evals don't count toward budgets
    await add_spend(session, 0.5, ts=datetime.now().astimezone() - timedelta(days=40))  # last month or earlier
    u = (await client.get("/api/usage")).json()
    assert u["today_usd"] == pytest.approx(0.85)
    assert u["month_usd"] == pytest.approx(0.85)
    assert u["month_by_purpose"]["eval"] == pytest.approx(3.0)
    assert (u["warn"], u["blocked"], u["reason"]) == (True, False, None)


async def test_daily_budget_blocks_turns_before_anything_is_stored(client, session, llm, budgets):
    tid = await new_thread(client)
    await add_spend(session, 1.0)
    res = await client.post(f"/api/threads/{tid}/turns", json={"action": "ask", "text": "hi"})
    assert res.status_code == 402
    assert "Daily budget reached" in res.json()["detail"]
    assert llm.calls == []
    assert (await client.get(f"/api/threads/{tid}")).json()["messages"] == []


async def test_monthly_budget_blocks_spark(client, session, budgets):
    light = FakeLightLLM()
    app.dependency_overrides[get_light_llm] = lambda: light
    try:
        await add_spend(session, 9.5, ts=datetime.now().astimezone().replace(day=1, hour=0, minute=1))
        await add_spend(session, 0.5)
        res = await client.post("/api/spark")
        assert res.status_code == 402 and "Monthly budget reached" in res.json()["detail"]
        assert light.calls == []
    finally:
        app.dependency_overrides.pop(get_light_llm, None)


async def test_zero_means_no_limit(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "daily_budget_usd", 0)
    monkeypatch.setattr(get_settings(), "monthly_budget_usd", 0)
    await add_spend(session, 500)
    assert not (await budget.spend(session, DEFAULT_USER_ID)).blocked


async def test_spark_is_recorded(client, session):
    light = FakeLightLLM(replies=[{"concept": "Baroreflex", "question": "q", "teaser": "t"}])
    app.dependency_overrides[get_light_llm] = lambda: light
    try:
        assert (await client.post("/api/spark")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_light_llm, None)
    assert [r.purpose for r in (await session.scalars(select(ApiCall))).all()] == ["spark"]
