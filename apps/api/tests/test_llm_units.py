from app.llm.card_schema import CARD_SCHEMA
from app.llm.client import replayable
from app.llm.partial import PartialJSON
from app.llm.prompt import NO_PROFILE, Notes, system_blocks, user_turn
from app.schemas import Branch, Card
from app.settings import get_settings


def test_card_schema_matches_pydantic_model():
    assert list(CARD_SCHEMA["properties"]) == list(Card.model_fields)
    assert CARD_SCHEMA["required"] == list(Card.model_fields)
    branch = CARD_SCHEMA["properties"]["branches"]["items"]
    assert list(branch["properties"]) == list(Branch.model_fields)


def test_partial_json_grows_with_the_stream():
    p = PartialJSON()
    assert p.parse() is None
    p.feed('{"concept": "Air cond')
    assert p.parse() == {"concept": "Air cond"}
    p.feed('itioning", "highlights": ["a", "b')
    assert p.parse() == {"concept": "Air conditioning", "highlights": ["a", "b"]}
    p.feed('"]}')
    assert p.parse() == {"concept": "Air conditioning", "highlights": ["a", "b"]}


def test_partial_json_handles_unicode_and_garbage():
    p = PartialJSON()
    p.feed('{"example": "−26 °C, caf')
    assert p.parse() == {"example": "−26 °C, caf"}
    bad = PartialJSON()
    bad.feed("not json")
    assert bad.parse() is None


def test_replayable_drops_internal_blocks_before_last_fallback():
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "a"},
        {"type": "text", "text": '{"concept": "X'},
        {"type": "fallback", "from": {"model": "m1"}, "to": {"model": "m2"}},
        {"type": "thinking", "thinking": "", "signature": "b"},
        {"type": "text", "text": '"}'},
    ]
    assert [b["type"] for b in replayable(blocks)] == ["text", "fallback", "thinking", "text"]
    no_fallback = blocks[:2]
    assert replayable(no_fallback) == no_fallback


def test_user_turn_header_notes_and_escaping():
    notes = Notes("Air conditioning", links=[("Heat pump", "same cycle"), ("Fridge", "")], takeaways=[("idea", "x?")])
    out = user_turn("dive", "mechanism", 'Say "hi"', "Go deeper.", notes)
    assert out.splitlines()[0] == '<turn action="dive" depth="mechanism" focus=\'Say "hi"\'/>'
    assert "- Heat pump: same cycle\n- Fridge\n" in out
    assert "- [idea] x?" in out
    assert out.endswith("<message>\nGo deeper.\n</message>")
    assert "<my_notes" not in user_turn("switch", "explain", None, "hi", Notes("X"))


def test_system_blocks_use_profile_file(tmp_path, monkeypatch):
    settings = get_settings()
    profile = tmp_path / "profile.md"
    monkeypatch.setattr(settings, "profile_path", profile)
    assert NO_PROFILE in system_blocks()[1]["text"]

    profile.write_text("Strong: statistics")
    blocks = system_blocks()
    assert "hook card" in blocks[0]["text"]
    assert blocks[1]["text"].endswith("Strong: statistics")
