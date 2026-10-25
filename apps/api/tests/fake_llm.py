import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import Final, StreamEvent, TextDelta, ThinkingStarted

THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}


def card(concept: str = "Air conditioning", kind: str = "intro", depth: str = "explain", **overrides) -> dict:
    c = {
        "concept": concept,
        "kind": kind,
        "depth": depth,
        "one_liner": f"{concept} in one line.",
        "example": "Touch the back of your fridge: it's warm.",
        "highlights": ["fact one", "fact two", "fact three"],
        "bridge": "A thermostat is a feedback controller.",
        "body_md": "",
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


@dataclass
class FakeLightLLM:
    """Replies to light-model calls: a queue of dicts (or exceptions), else a default title."""

    replies: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def json(self, system, prompt, schema):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        reply = self.replies.pop(0) if self.replies else {"title": "Generated title"}
        if isinstance(reply, Exception):
            raise reply
        return reply


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
