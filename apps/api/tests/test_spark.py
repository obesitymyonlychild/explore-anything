import random
from datetime import UTC, datetime, timedelta

import anthropic
import httpx2
import pytest

from app.llm.light import get_light_llm
from app.main import app
from app.models import InterestEvent
from app.services import spark as spark_service
from app.settings import DEFAULT_USER_ID
from tests.fake_llm import FakeLightLLM


@pytest.fixture
def light():
    fake = FakeLightLLM()
    app.dependency_overrides[get_light_llm] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_light_llm, None)


def test_topic_areas_file_is_clean():
    areas = spark_service.topic_areas()
    assert len(areas) >= 30
    assert len(set(areas)) == len(areas)
    assert not any(a.startswith("#") for a in areas)


async def test_spark_returns_a_concept_and_avoids_known_ones(client, light):
    await client.post("/api/concepts", json={"name": "Heat pump"})
    light.replies.append({"concept": "  Thermal expansion joint ", "teaser": "Bridges have gaps on purpose."})

    res = await client.post("/api/spark")
    assert res.status_code == 200
    body = res.json()
    assert body["concept"] == "Thermal expansion joint"
    assert body["topic_area"] in spark_service.topic_areas()
    prompt = light.calls[0]["prompt"]
    assert f"Topic area: {body['topic_area']}" in prompt
    assert "- Heat pump" in prompt


async def test_recent_topic_areas_are_skipped(session):
    areas = spark_service.topic_areas()
    now = datetime.now(UTC)
    # areas[0] was used 11 sparks ago (no longer recent); areas[1..10] are the 10 most recent.
    for i, area in enumerate(areas[:11]):
        ts = now - timedelta(minutes=11 - i)
        session.add(InterestEvent(user_id=DEFAULT_USER_ID, action="spark_shown", meta={"topic_area": area}, ts=ts))
    await session.commit()

    picks = {await spark_service.pick_topic_area(session, DEFAULT_USER_ID, random.Random(seed)) for seed in range(200)}
    assert picks.isdisjoint(areas[1:11])
    assert areas[0] in picks


@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (
            anthropic.AuthenticationError(
                "bad", response=httpx2.Response(401, request=httpx2.Request("POST", "https://x")), body=None
            ),
            "ANTHROPIC_API_KEY",
        ),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "Try again"),
        ({"teaser": "missing concept"}, "Try again"),
    ],
)
async def test_spark_errors_are_502(client, light, exc, needle):
    light.replies.append(exc)
    res = await client.post("/api/spark")
    assert res.status_code == 502
    assert needle in res.json()["detail"]
