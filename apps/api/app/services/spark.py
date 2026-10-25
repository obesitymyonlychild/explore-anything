"""Surprise me (MVP): a random topic area, then the light model picks one intriguing concept in it.

P3 replaces the uniform random pick with an interest-weighted one; the interface stays the same.
"""

import random
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.light import LightLLM
from app.models import Concept, InterestEvent
from app.settings import get_settings

RECENT_AREAS = 10  # don't repeat a topic area from the last N sparks
KNOWN_CONCEPTS = 300  # most recent concept names passed in, to avoid repeats

SYSTEM = """You pick one concept for a curious adult to explore next, inside a given topic area.

Pick something specific (a mechanism, phenomenon, invention or idea, not a whole field) that is \
surprising, concrete, and explainable with everyday examples: the kind of thing that makes someone \
say "wait, how does that work?". Avoid anything in the list of concepts the user already knows.

`concept` is the canonical name as a short noun phrase in Title case ("Thermal expansion joint"). \
`teaser` is one sentence, under 20 words, that makes the concept irresistible without explaining it."""

SCHEMA = {
    "type": "object",
    "properties": {"concept": {"type": "string"}, "teaser": {"type": "string"}},
    "required": ["concept", "teaser"],
    "additionalProperties": False,
}


def topic_areas() -> list[str]:
    path = get_settings().prompts_dir / "topic_areas.txt"
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


async def pick_topic_area(session: AsyncSession, user_id: uuid.UUID, rng: random.Random) -> str:
    recent = await session.scalars(
        select(InterestEvent.meta["topic_area"].astext)
        .where(InterestEvent.user_id == user_id, InterestEvent.action == "spark_shown")
        .order_by(InterestEvent.ts.desc())
        .limit(RECENT_AREAS)
    )
    recent_set = {a for a in recent if a}
    areas = topic_areas()
    return rng.choice([a for a in areas if a not in recent_set] or areas)


async def spark(
    session: AsyncSession, user_id: uuid.UUID, llm: LightLLM, rng: random.Random | None = None
) -> dict[str, str]:
    area = await pick_topic_area(session, user_id, rng or random.Random())
    known = (
        await session.scalars(
            select(Concept.name)
            .where(Concept.user_id == user_id)
            .order_by(Concept.created_at.desc())
            .limit(KNOWN_CONCEPTS)
        )
    ).all()
    prompt = f"Topic area: {area}\n\nConcepts the user already knows:\n" + (
        "\n".join(f"- {name}" for name in known) or "(none yet)"
    )
    result = await llm.json(SYSTEM, prompt, SCHEMA)
    return {"concept": result["concept"].strip(), "teaser": result["teaser"].strip(), "topic_area": area}
