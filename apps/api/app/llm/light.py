"""Small, cheap structured calls on the light model (Surprise me picks, thread titles)."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from app.llm.partial import PartialJSON
from app.settings import get_settings


class LightLLMError(Exception):
    """The call completed (and was billed) but gave no usable answer."""

    def __init__(self, message: str, model: str = "", usage: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.model = model
        self.usage = usage or {}


@dataclass
class LightResult:
    data: dict[str, Any]
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


class LightLLM(Protocol):
    async def json(self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 4000) -> LightResult:
        """Return the model's reply, constrained to `schema`. Raises LightLLMError or anthropic.APIError."""
        ...

    def stream_json(
        self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 4000
    ) -> AsyncIterator[dict[str, Any] | LightResult]:
        """Like json(), but yields the partial reply (a dict) as it grows, then the LightResult."""
        ...


class AnthropicLightLLM:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.settings = get_settings()
        self.client = client or anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key or None)

    async def json(self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 4000) -> LightResult:
        response = await self.client.messages.create(
            model=self.settings.light_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        usage = response.usage.model_dump(mode="json", exclude_none=True)
        if response.stop_reason != "end_turn":
            raise LightLLMError(f"stop_reason={response.stop_reason}", response.model, usage)
        text = next((b.text for b in response.content if b.type == "text"), "")
        return LightResult(json.loads(text), response.model, usage)

    async def stream_json(
        self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 4000
    ) -> AsyncIterator[dict[str, Any] | LightResult]:
        parser = PartialJSON()
        async with self.client.messages.stream(
            model=self.settings.light_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    parser.feed(event.delta.text)
                    partial = parser.parse()
                    if partial:
                        yield partial
            final = await stream.get_final_message()
        usage = final.usage.model_dump(mode="json", exclude_none=True)
        if final.stop_reason != "end_turn":
            raise LightLLMError(f"stop_reason={final.stop_reason}", final.model, usage)
        yield LightResult(json.loads(parser.text), final.model, usage)


_light: LightLLM | None = None


def get_light_llm() -> LightLLM:
    """FastAPI dependency; overridden in tests."""
    global _light
    if _light is None:
        _light = AnthropicLightLLM()
    return _light
