"""Card diagrams: which kinds exist, and the clean-up applied before a card is stored.

The page draws each kind itself (app/static/app.js), so Claude only supplies structured items:
    flow      ordered steps                          label, detail
    cycle     a loop that repeats                    label, detail
    timeline  when things happen (time in `label`)   label, detail
    compare   two things side by side                columns = [A, B]; label = aspect, detail = A, detail_b = B
    bars      quantities in one unit                 label, value (> 0), value_text; detail optional
    causes    factors that produce one outcome       title = outcome; label, detail per factor
"""

from typing import Any

MIN_ITEMS = {"flow": 2, "cycle": 3, "timeline": 2, "compare": 2, "bars": 2, "causes": 2}
MAX_ITEMS = {"flow": 6, "cycle": 6, "timeline": 7, "compare": 5, "bars": 6, "causes": 5}

EMPTY = {"kind": "none", "title": "", "columns": [], "items": []}


def clean(diagram: dict[str, Any]) -> dict[str, Any]:
    """Drop diagrams the page can't draw well instead of showing something broken."""
    kind = diagram.get("kind", "none")
    if kind not in MIN_ITEMS:
        return dict(EMPTY)
    items = [i for i in diagram.get("items", []) if i.get("label", "").strip()]
    if kind == "bars":
        items = [i for i in items if isinstance(i.get("value"), (int, float)) and i["value"] > 0]
    if kind == "compare":
        columns = [c for c in diagram.get("columns", []) if c.strip()]
        if len(columns) != 2:
            return dict(EMPTY)
    else:
        columns = []
    if len(items) < MIN_ITEMS[kind]:
        return dict(EMPTY)
    return {"kind": kind, "title": diagram.get("title", ""), "columns": columns, "items": items[: MAX_ITEMS[kind]]}


def items_of(diagram: dict[str, Any]) -> list[dict[str, Any]]:
    """Items of a stored diagram, including the pre-2026-10-28 shape ({steps: [{label, detail}]})."""
    if "items" in diagram:
        return diagram["items"]
    return [
        {"label": s["label"], "detail": s["detail"], "detail_b": "", "value": 0, "value_text": ""}
        for s in diagram.get("steps", [])
    ]
