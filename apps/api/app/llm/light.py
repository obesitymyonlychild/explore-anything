"""Small, cheap structured calls on the light model (Surprise me picks, thread titles)."""

import json
from typing import Any, Protocol

import anthropic

from app.settings import get_settings


class LightLLMError(Exception):
    pass


class LightLLM(Protocol):
    async def json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return the model's reply, constrained to `schema`. Raises LightLLMError or anthropic.APIError."""
        ...


class AnthropicLightLLM:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.settings = get_settings()
        self.client = client or anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key or None)

    async def json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.messages.create(
            model=self.settings.light_model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason != "end_turn":
            raise LightLLMError(f"stop_reason={response.stop_reason}")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return json.loads(text)


_light: LightLLM | None = None


def get_light_llm() -> LightLLM:
    """FastAPI dependency; overridden in tests."""
    global _light
    if _light is None:
        _light = AnthropicLightLLM()
    return _light
