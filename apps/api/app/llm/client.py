"""Thin wrapper around the Anthropic SDK for streaming hook cards.

The orchestrator only depends on the `CardLLM` protocol, so tests swap in a fake that
replays recorded text without calling the API.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from app.llm.card_schema import OUTPUT_FORMAT
from app.settings import get_settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingStarted:
    """Claude started reasoning; at deeper levels this can take 10+ s before any text."""


@dataclass
class Final:
    content: list[dict[str, Any]]  # content blocks to store and replay verbatim
    stop_reason: str | None
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


StreamEvent = TextDelta | ThinkingStarted | Final


class CardLLM(Protocol):
    def stream_card(self, system: list[dict[str, Any]], messages: list[dict[str, Any]]) -> AsyncIterator[StreamEvent]:
        """Yield ThinkingStarted / TextDelta events for the card's JSON text, then exactly one Final."""
        ...


def replayable(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Content blocks safe to send back as history.

    After a mid-output server-side fallback, model-internal blocks (thinking, tool use)
    that appear before the last `fallback` block must be omitted; everything else is
    echoed unchanged.
    """
    last_fallback = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    internal = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(blocks) if not (i < last_fallback and b.get("type") in internal)]


class AnthropicCardLLM:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.settings = get_settings()
        self.client = client or anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key or None)

    async def stream_card(
        self, system: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> AsyncIterator[StreamEvent]:
        s = self.settings
        extra: dict[str, Any] = {}
        if s.chat_fallbacks:
            # On a safety-classifier refusal, the API retries on Anthropic's recommended model.
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}

        async with self.client.beta.messages.stream(
            model=s.chat_model,
            max_tokens=s.chat_max_tokens,
            system=system,
            messages=messages,
            output_config={"effort": s.chat_effort, "format": OUTPUT_FORMAT},
            cache_control={"type": "ephemeral"},  # caches the growing prefix (system + history)
            **extra,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield TextDelta(event.delta.text)
                elif event.type == "content_block_start" and event.content_block.type == "thinking":
                    yield ThinkingStarted()
            final = await stream.get_final_message()

        blocks = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in final.content]
        yield Final(
            content=replayable(blocks),
            stop_reason=final.stop_reason,
            model=final.model,
            usage=final.usage.model_dump(mode="json", exclude_none=True),
        )


_llm: CardLLM | None = None


def get_llm() -> CardLLM:
    """FastAPI dependency; overridden in tests."""
    global _llm
    if _llm is None:
        _llm = AnthropicCardLLM()
    return _llm
