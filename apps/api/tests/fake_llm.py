import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import Final, StreamEvent, TextDelta, ThinkingStarted
from app.llm.light import LightResult

THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}


def item(label: str, detail: str = "", detail_b: str = "", value: float = 0, value_text: str = "") -> dict:
    return {"label": label, "detail": detail, "detail_b": detail_b, "value": value, "value_text": value_text}


def card(concept: str = "Air conditioning", kind: str = "intro", depth: str = "explain", **overrides) -> dict:
    c = {
        "concept": concept,
        "kind": kind,
        "depth": depth,
        "one_liner": f"{concept} in one line.",
        "example": "Touch the back of your fridge: it's warm.",
        "diagram": {
            "kind": "cycle",
            "title": "The refrigerant loop",
            "columns": [],
            "items": [
                item("Evaporate indoors", "absorbs room heat"),
                item("Compress", "gets hotter than outside"),
                item("Condense outdoors", "dumps the heat"),
                item("Expand", "gets cold again"),
            ],
        },
        "highlights": ["fact one", "fact two", "fact three"],
        "bridge": "A thermostat is a feedback controller.",
        "body_md": "",
        "pictures": [{"wikipedia_title": "Vapor-compression refrigeration", "caption": "the four stages"}],
        "branches": [
            {"kind": "deeper", "label": "Go deeper", "concept": concept},
            {"kind": "related", "label": "Heat pumps", "concept": "Heat pump"},
            {"kind": "related", "label": "Refrigerants", "concept": "Refrigerant"},
            {"kind": "switch", "label": "Something else", "concept": ""},
        ],
    }
    c.update(overrides)
    return c


@dataclass
class Script:
    """One scripted reply: raw JSON text (streamed in small chunks) and how it ends."""

    text: str
    stop_reason: str = "end_turn"
    raise_exc: Exception | None = None

    @classmethod
    def of(cls, c: dict, **kw) -> "Script":
        return cls(json.dumps(c), **kw)


def _mark(value):
    if isinstance(value, str):
        return f"中:{value}" if value else ""
    if isinstance(value, list):
        return [_mark(v) for v in value]
    if isinstance(value, dict):
        return {k: _mark(v) for k, v in value.items()}
    return value


@dataclass
class FakeLightLLM:
    """Replies to light-model calls: a queue of dicts (or exceptions), else a default title."""

    replies: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def json(self, system, prompt, schema, max_tokens=4000):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        if self.replies:
            reply = self.replies.pop(0)
        elif "branch_labels" in schema["properties"]:  # a card translation: echo the card, marked
            reply = _mark(json.loads(prompt))
        else:
            reply = {"title": "Generated title"}
        if isinstance(reply, Exception):
            raise reply
        return LightResult(reply, "claude-haiku-5-5", {"input_tokens": 1000, "output_tokens": 100})

    async def stream_json(self, system, prompt, schema, max_tokens=4000):
        result = await self.json(system, prompt, schema, max_tokens)
        first_key = next(iter(result.data), None)
        if first_key is not None:
            yield {first_key: result.data[first_key]}  # one partial, then the whole reply
        yield result


@dataclass
class FakeLLM:
    scripts: list[Script] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def stream_card(self, system, messages) -> AsyncIterator[StreamEvent]:
        self.calls.append({"system": system, "messages": json.loads(json.dumps(messages))})
        script = self.scripts.pop(0)
        if script.raise_exc:
            raise script.raise_exc
        yield ThinkingStarted()
        for i in range(0, len(script.text), 7):
            yield TextDelta(script.text[i : i + 7])
        yield Final(
            content=[THINKING, {"type": "text", "text": script.text}],
            stop_reason=script.stop_reason,
            model="claude-opus-5-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
