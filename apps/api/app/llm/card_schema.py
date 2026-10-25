"""JSON Schema for the hook card, sent as `output_config.format`.

Written by hand (not generated from schemas.Card) so the property order, which is also the
order fields stream in, is explicit. tests/test_card_schema.py keeps the two in sync.
"""

from typing import Any

_str: dict[str, Any] = {"type": "string"}

CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concept": {**_str, "description": "Canonical name of the concept this card is about."},
        "kind": {"type": "string", "enum": ["intro", "deeper", "answer"]},
        "depth": {"type": "string", "enum": ["glance", "explain", "mechanism", "expert"]},
        "one_liner": _str,
        "example": _str,
        "highlights": {"type": "array", "items": _str},
        "bridge": _str,
        "body_md": _str,
        "branches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["deeper", "related", "switch"]},
                    "label": _str,
                    "concept": _str,
                },
                "required": ["kind", "label", "concept"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["concept", "kind", "depth", "one_liner", "example", "highlights", "bridge", "body_md", "branches"],
    "additionalProperties": False,
}

OUTPUT_FORMAT: dict[str, Any] = {"type": "json_schema", "schema": CARD_SCHEMA}
