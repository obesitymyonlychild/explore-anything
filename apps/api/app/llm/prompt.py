"""Prompt assembly.

Everything that changes per turn (action, depth, the user's notes) goes into the user
message, so the system prompt (the cached prefix) stays byte-identical across turns.
"""

from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import quoteattr

from app.settings import get_settings

NO_PROFILE = "(No profile provided. Assume a curious, technically literate adult.)"


@dataclass
class Notes:
    """The user's own layer for one concept."""

    concept: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (other concept, note)
    takeaways: list[tuple[str, str]] = field(default_factory=list)  # (kind, body)

    def __bool__(self) -> bool:
        return bool(self.links or self.takeaways)


def system_blocks() -> list[dict[str, Any]]:
    s = get_settings()
    rules = (s.prompts_dir / "system.md").read_text()
    profile = s.profile_path.read_text().strip() if s.profile_path.exists() else NO_PROFILE
    return [
        {"type": "text", "text": rules},
        {"type": "text", "text": f"## The user's expertise profile\n\n{profile}"},
    ]


def user_turn(action: str, depth: str, focus: str | None, text: str, notes: Notes | None = None) -> str:
    attrs = f"action={quoteattr(action)} depth={quoteattr(depth)}"
    if focus:
        attrs += f" focus={quoteattr(focus)}"
    parts = [f"<turn {attrs}/>"]

    if notes:
        lines = [f"<my_notes concept={quoteattr(notes.concept)}>"]
        if notes.links:
            lines.append("links I drew:")
            lines += [f"- {other}" + (f": {note}" if note else "") for other, note in notes.links]
        if notes.takeaways:
            lines.append("my takeaways:")
            lines += [f"- [{kind}] {body}" for kind, body in notes.takeaways]
        lines.append("</my_notes>")
        parts.append("\n".join(lines))

    parts.append(f"<message>\n{text}\n</message>")
    return "\n".join(parts)
