from typing import Any

import jiter


class PartialJSON:
    """Accumulates streamed JSON text and parses whatever is complete so far.

    `trailing-strings` mode keeps a half-written string value, so a field like
    `example` grows word by word in the UI instead of appearing all at once.
    """

    def __init__(self) -> None:
        self.text = ""

    def feed(self, chunk: str) -> None:
        self.text += chunk

    def parse(self) -> dict[str, Any] | None:
        if not self.text.strip():
            return None
        try:
            value = jiter.from_json(self.text.encode(), partial_mode="trailing-strings")
        except ValueError:
            return None
        return value if isinstance(value, dict) else None
