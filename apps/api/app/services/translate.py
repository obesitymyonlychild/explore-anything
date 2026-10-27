"""Simplified Chinese for a finished card, written by the light model.

English stays the source of truth (it's what the history, concept names and branches use); the
Chinese is stored next to it as `card["zh"]` with the same shape for every text field.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.llm.light import LightLLM, LightResult

SYSTEM = """You translate cards from a learning app into Simplified Chinese (简体中文) for a reader \
who is fluent in both languages and is learning the topic.

- Translate every field; keep empty strings empty and keep every list the same length and order.
- Sound natural, not word-for-word. Keep the meaning, numbers and units exactly.
- Technical terms: use the standard Chinese term, and add the English in brackets the first time it \
appears in the card, e.g. 制冷剂 (refrigerant). Brackets are only for English technical terms: never \
bracket everyday words, names of people or places, or alternative Chinese names.
- `concept` is the card's title, shown next to the English name: give the Chinese name only, with no \
brackets. The bracket rule above applies from the other fields on.
- Keep Markdown formatting (bold, lists) in `body_md`.
- Names of people, companies and products: use the common Chinese name if one exists, else keep English."""

_str: dict[str, Any] = {"type": "string"}
_list = {"type": "array", "items": _str}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concept": _str,
        "one_liner": _str,
        "example": _str,
        "diagram_title": _str,
        "diagram_steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": _str, "detail": _str},
                "required": ["label", "detail"],
                "additionalProperties": False,
            },
        },
        "highlights": _list,
        "bridge": _str,
        "body_md": _str,
        "captions": _list,
        "branch_labels": _list,
    },
    "required": [
        "concept",
        "one_liner",
        "example",
        "diagram_title",
        "diagram_steps",
        "highlights",
        "bridge",
        "body_md",
        "captions",
        "branch_labels",
    ],
    "additionalProperties": False,
}
MAX_TOKENS = 8000  # deep cards' body_md can run to ~2k tokens of English


def payload(card: dict[str, Any]) -> dict[str, Any]:
    """The card's text fields, in the translation schema's shape."""
    diagram = card.get("diagram") or {}
    return {
        "concept": card.get("concept", ""),
        "one_liner": card.get("one_liner", ""),
        "example": card.get("example", ""),
        "diagram_title": diagram.get("title", ""),
        "diagram_steps": [{"label": s["label"], "detail": s["detail"]} for s in diagram.get("steps", [])],
        "highlights": list(card.get("highlights", [])),
        "bridge": card.get("bridge", ""),
        "body_md": card.get("body_md", ""),
        "captions": [i.get("caption", "") for i in card.get("images", [])],
        "branch_labels": [b["label"] for b in card.get("branches", [])],
    }


def _fit(items: list, n: int, empty: Any) -> list:
    """Same length as the English list, so the page can pair them by index."""
    return (list(items) + [empty] * n)[:n]


def _fitted(zh: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    zh = dict(zh)
    for key in ("highlights", "captions", "branch_labels"):
        zh[key] = _fit(zh.get(key, []), len(source[key]), "")
    zh["diagram_steps"] = _fit(zh.get("diagram_steps", []), len(source["diagram_steps"]), {"label": "", "detail": ""})
    return zh


async def translate_card(llm: LightLLM, card: dict[str, Any]) -> tuple[dict[str, Any], LightResult]:
    """(zh, result for the cost ledger). Raises LightLLMError or anthropic.APIError."""
    source = payload(card)
    result = await llm.json(SYSTEM, json.dumps(source, ensure_ascii=False), SCHEMA, max_tokens=MAX_TOKENS)
    return _fitted(result.data, source), result


async def stream_translation(
    llm: LightLLM, card: dict[str, Any]
) -> AsyncIterator[dict[str, Any] | tuple[dict[str, Any], LightResult]]:
    """Yields the partial Chinese as it's written (a dict), then (zh, result) once complete.
    Raises LightLLMError or anthropic.APIError."""
    source = payload(card)
    async for item in llm.stream_json(SYSTEM, json.dumps(source, ensure_ascii=False), SCHEMA, max_tokens=MAX_TOKENS):
        if isinstance(item, LightResult):
            yield _fitted(item.data, source), item
        else:
            yield item
