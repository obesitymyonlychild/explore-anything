"""Small, cheap structured calls on the light model (Surprise me picks, thread titles)."""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

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
    async def json(self, system: str, prompt: str, schema: dict[str, Any]) -> LightResult:
        """Return the model's reply, constrained to `schema`. Raises LightLLMError or anthropic.APIError."""
        ...


class AnthropicLightLLM:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.settings = get_settings()
        self.client = client or anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key or None)

    async def json(self, system: str, prompt: str, schema: dict[str, Any]) -> LightResult:
        response = await self.client.messages.create(
            model=self.settings.light_model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        usage = response.usage.model_dump(mode="json", exclude_none=True)
        if response.stop_reason != "end_turn":
            raise LightLLMError(f"stop_reason={response.stop_reason}", response.model, usage)
        text = next((b.text for b in response.content if b.type == "text"), "")
        return LightResult(json.loads(text), response.model, usage)


_light: LightLLM | None = None


def get_light_llm() -> LightLLM:
    """FastAPI dependency; overridden in tests."""
    global _light
    if _light is None:
        _light = AnthropicLightLLM()
    return _light
