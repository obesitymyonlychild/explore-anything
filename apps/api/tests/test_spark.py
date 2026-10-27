import random
from datetime import UTC, datetime, timedelta

import anthropic
import httpx2
import pytest
from sqlalchemy import select

from app.llm.light import get_light_llm
from app.main import app
from app.models import InterestEvent
from app.services import spark as spark_service
from app.settings import DEFAULT_USER_ID
from tests.fake_llm import FakeLightLLM, Script, card
from tests.test_turns import new_thread, turn


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
    light.replies.append(
        {"concept": "  Thermal expansion joint ", "question": " Why do bridges have gaps? ", "teaser": "On purpose."}
    )

    res = await client.post("/api/spark")
    assert res.status_code == 200
    body = res.json()
    assert body["concept"] == "Thermal expansion joint"
    assert body["question"] == "Why do bridges have gaps?"
    assert body["topic_area"] in spark_service.topic_areas()
    assert body["angle"] in {a.key for a in spark_service.angles()}
    prompt = light.calls[0]["prompt"]
    assert f"Topic area: {body['topic_area']}" in prompt
    assert f"Angle: {body['angle']}: " in prompt
    assert "- Heat pump" in prompt


def test_angles_file_is_clean():
    angles = spark_service.angles()
    keys = [a.key for a in angles]
    assert len(keys) == len(set(keys)) >= 8
    assert all(a.weight > 0 and a.about and a.example.endswith("?") for a in angles)
    share = {a.key: a.weight / sum(x.weight for x in angles) for a in angles}
    assert share["how-it-works"] <= 0.2  # the point of angles: mechanisms are a minority


async def test_recent_angles_are_skipped(session):
    now = datetime.now(UTC)
    for i, key in enumerate(["how-it-works", "day-in-the-life", "place"]):
        session.add(
            InterestEvent(
                user_id=DEFAULT_USER_ID, action="spark_shown", meta={"angle": key}, ts=now - timedelta(minutes=3 - i)
            )
        )
    await session.commit()
    picks = {(await spark_service.pick_angle(session, DEFAULT_USER_ID, random.Random(seed))).key for seed in range(300)}
    assert picks.isdisjoint({"how-it-works", "day-in-the-life", "place"})
    assert len(picks) >= 6


def test_angle_weights_shape_the_mix():
    rng = random.Random(0)
    angles = spark_service.angles()
    counts = {}
    for _ in range(4000):
        key = rng.choices(angles, weights=[a.weight for a in angles])[0].key
        counts[key] = counts.get(key, 0) + 1
    assert 0.10 < counts["how-it-works"] / 4000 < 0.20


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


# --- skips and feedback weighting ---------------------------------------------

PICK = {"concept": "Glassblowing", "question": "How do glassblowers judge molten glass?", "teaser": "By colour."}


async def spark_thread(client, llm, area="Art, museums and design", angle="craft-and-skill") -> str:
    llm.scripts.append(Script.of(card("Glassblowing")))
    tid = await new_thread(client)
    await turn(client, tid, action="spark", concept="Glassblowing", text=PICK["question"], topic_area=area, angle=angle)
    return tid


async def skips(session) -> list[InterestEvent]:
    return (await session.scalars(select(InterestEvent).where(InterestEvent.action == "skip"))).all()


async def test_asking_for_another_spark_skips_an_untouched_one(client, session, llm, light):
    tid = await spark_thread(client, llm)
    light.replies.append(dict(PICK))
    assert (await client.post("/api/spark")).status_code == 200

    (skip,) = await skips(session)
    assert str(skip.thread_id) == tid
    assert skip.meta == {
        "how": "implicit",
        "concept": "Glassblowing",
        "topic_area": "Art, museums and design",
        "angle": "craft-and-skill",
    }

    light.replies.append(dict(PICK))
    await client.post("/api/spark")
    assert len(await skips(session)) == 1  # never twice for the same spark


async def test_engaging_with_a_spark_is_not_a_skip(client, session, llm, light):
    tid = await spark_thread(client, llm)
    llm.scripts.append(Script.of(card("Glassblowing", kind="dive", depth="deep")))
    await turn(client, tid, action="dive")
    light.replies.append(dict(PICK))
    await client.post("/api/spark")
    assert await skips(session) == []


async def test_not_interested_marks_the_spark(client, session, llm, light):
    tid = await spark_thread(client, llm)
    res = await client.post(f"/api/threads/{tid}/not-interested")
    assert res.status_code == 204
    light.replies.append(dict(PICK))
    await client.post("/api/spark")  # doesn't add an implicit skip on top
    (skip,) = await skips(session)
    assert skip.meta["how"] == "not_interested"

    llm.scripts.append(Script.of(card()))
    plain = await new_thread(client)
    await turn(client, plain, action="ask", text="What is air conditioning?")
    assert (await client.post(f"/api/threads/{plain}/not-interested")).status_code == 404


async def test_skipped_areas_and_angles_come_up_less(session):
    areas = spark_service.topic_areas()
    liked, disliked = areas[0], areas[1]
    now = datetime.now(UTC)
    rows = [("spark_shown", {"topic_area": liked, "angle": "place"})] * 3
    for how in ("implicit", "not_interested"):
        meta = {"topic_area": disliked, "angle": "how-it-works"}
        rows += [("spark_shown", meta), ("skip", {**meta, "how": how})]
    for i, (action, meta) in enumerate(rows):
        session.add(
            InterestEvent(user_id=DEFAULT_USER_ID, action=action, meta=meta, ts=now - timedelta(days=1, minutes=i))
        )
    await session.commit()

    areas_f = await spark_service.feedback_factors(session, DEFAULT_USER_ID, "topic_area")
    assert areas_f[liked] == spark_service.MAX_FACTOR
    assert areas_f[disliked] == pytest.approx(1 / 4)  # no kept sparks, penalty 1 + 2
    angles_f = await spark_service.feedback_factors(session, DEFAULT_USER_ID, "angle")
    assert angles_f["how-it-works"] < 1 < angles_f["place"]

    # Push both out of the "recent" window so only the weights matter.
    filler = [a for a in areas if a not in (liked, disliked)]
    for i in range(spark_service.RECENT_AREAS):
        session.add(
            InterestEvent(
                user_id=DEFAULT_USER_ID,
                action="spark_shown",
                meta={"topic_area": filler[i]},
                ts=now - timedelta(minutes=i),
            )
        )
    await session.commit()
    counts = {liked: 0, disliked: 0}
    for seed in range(3000):
        pick = await spark_service.pick_topic_area(session, DEFAULT_USER_ID, random.Random(seed))
        if pick in counts:
            counts[pick] += 1
    assert counts[liked] > 4 * counts[disliked] > 0  # less likely, never ruled out
