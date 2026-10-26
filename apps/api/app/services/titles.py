import logging

from app.llm.light import LightLLM, LightLLMError, LightResult
from app.schemas import Card

log = logging.getLogger(__name__)

SYSTEM = """Name a conversation thread in a learning app. Reply with a title of 2 to 5 words that \
captures what the user wanted to know, in sentence case and without quotes or a trailing period \
("How air conditioners move heat", "Why bridges sway")."""

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

MAX_LEN = 60


async def generate_title(llm: LightLLM, first_message: str, card: Card) -> tuple[str | None, LightResult | None]:
    """(title, result for the cost ledger). The title is None if generation fails, and the
    provisional title then stays."""
    prompt = f"User's first message: {first_message}\n\nFirst answer, about {card.concept}: {card.one_liner}"
    try:
        result = await llm.json(SYSTEM, prompt, SCHEMA)
    except LightLLMError as e:  # billed but unusable: still goes in the ledger
        log.warning("title generation gave no answer: %s", e)
        return None, LightResult({}, e.model, e.usage)
    except Exception:  # a title is never worth failing a turn over
        log.warning("title generation failed", exc_info=True)
        return None, None
    title = " ".join(result.data.get("title", "").split()).strip("\"'. ")
    return title[:MAX_LEN] or None, result
