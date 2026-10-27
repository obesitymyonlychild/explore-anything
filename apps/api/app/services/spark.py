"""Surprise me: a random topic area x a random angle, then the light model frames one question.

The area says what it's about (prompts/topic_areas.txt); the angle says what kind of question it is
(prompts/spark_angles.txt: how it works, a day in the life, why it is so, …). Picking them separately
keeps the mix varied: without angles nearly every pick became "how does X work".

P3 replaces the uniform/weighted random picks with interest-weighted ones; the interface stays the same.
"""

import random
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.light import LightLLM
from app.models import Concept, InterestEvent
from app.services import budget
from app.settings import get_settings

RECENT_AREAS = 10  # don't repeat a topic area from the last N sparks
RECENT_ANGLES = 3  # nor an angle from the last N
KNOWN_CONCEPTS = 300  # most recent concept names passed in, to avoid repeats

SYSTEM = """You pick the next thing for a curious adult to explore, given a topic area and an angle.

The angle decides what kind of question it is; the topic area is where to look. Pick one specific \
subject (a particular job, device, place, person, custom, business, number, debate…, not a whole \
field) that fits the angle, sits in or near the area, and makes someone think "huh, I've always \
wondered about that" or "I never knew that was a thing". Avoid anything in the list of concepts the \
user already knows, and avoid the most obvious textbook example.

- `concept`: the subject's canonical name as a short noun phrase in Title case ("Air traffic \
controller", "QWERTY layout", "Venice").
- `question`: the question the card will answer, phrased for this angle, in under 15 words. It must \
name the subject itself ("What did Arthur Morris's idea do for credit cards?", never "this banker"). \
Use plain, varied wording of your own; don't reuse the example's phrasing or lean on "actually".
- Never build a question on a false or unproven premise. For myths, legends and fringe claims, ask \
about the belief, its origin or why people held it ("Why did people think the Ark of the Covenant \
was dangerous?"), not about how the claimed effect works.
- `teaser`: one sentence, under 20 words, that makes it irresistible without answering it."""

SCHEMA = {
    "type": "object",
    "properties": {
        "concept": {"type": "string"},
        "question": {"type": "string"},
        "teaser": {"type": "string"},
    },
    "required": ["concept", "question", "teaser"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Angle:
    key: str
    weight: float
    about: str
    example: str


def _lines(name: str) -> list[str]:
    path = get_settings().prompts_dir / name
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def topic_areas() -> list[str]:
    return _lines("topic_areas.txt")


def angles() -> list[Angle]:
    out = []
    for line in _lines("spark_angles.txt"):
        key, weight, about, example = (part.strip() for part in line.split("|"))
        out.append(Angle(key, float(weight), about, example))
    return out


async def _recent(session: AsyncSession, user_id: uuid.UUID, field: str, n: int) -> set[str]:
    rows = await session.scalars(
        select(InterestEvent.meta[field].astext)
        .where(InterestEvent.user_id == user_id, InterestEvent.action == "spark_shown")
        .order_by(InterestEvent.ts.desc())
        .limit(n)
    )
    return {r for r in rows if r}


async def pick_topic_area(session: AsyncSession, user_id: uuid.UUID, rng: random.Random) -> str:
    recent = await _recent(session, user_id, "topic_area", RECENT_AREAS)
    areas = topic_areas()
    return rng.choice([a for a in areas if a not in recent] or areas)


async def pick_angle(session: AsyncSession, user_id: uuid.UUID, rng: random.Random) -> Angle:
    recent = await _recent(session, user_id, "angle", RECENT_ANGLES)
    pool = [a for a in angles() if a.key not in recent] or angles()
    return rng.choices(pool, weights=[a.weight for a in pool])[0]


async def spark(
    session: AsyncSession, user_id: uuid.UUID, llm: LightLLM, rng: random.Random | None = None
) -> dict[str, str]:
    rng = rng or random.Random()
    area = await pick_topic_area(session, user_id, rng)
    angle = await pick_angle(session, user_id, rng)
    known = (
        await session.scalars(
            select(Concept.name)
            .where(Concept.user_id == user_id)
            .order_by(Concept.created_at.desc())
            .limit(KNOWN_CONCEPTS)
        )
    ).all()
    prompt = (
        f"Angle: {angle.key}: {angle.about}. For example: {angle.example}\n"
        f"Topic area: {area}\n\n"
        "Concepts the user already knows:\n" + ("\n".join(f"- {name}" for name in known) or "(none yet)")
    )
    result = await llm.json(SYSTEM, prompt, SCHEMA)
    budget.record(session, user_id, "spark", result.model, result.usage)
    await session.commit()
    data = result.data
    return {
        "concept": data["concept"].strip(),
        "question": data["question"].strip(),
        "teaser": data["teaser"].strip(),
        "topic_area": area,
        "angle": angle.key,
    }
