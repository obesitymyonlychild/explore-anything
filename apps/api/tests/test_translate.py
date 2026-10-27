import uuid

import pytest
from sqlalchemy import select

from app.models import ApiCall, Message
from app.services import translate
from app.settings import get_settings
from tests.fake_llm import FakeLightLLM, Script, card
from tests.test_turns import new_thread, turn


async def stored_card(session, message_id):
    msg = await session.get(Message, uuid.UUID(message_id), populate_existing=True)
    return msg.card


async def test_each_card_gets_chinese_after_done(client, session, llm, light):
    llm.scripts += [Script.of(card()), Script.of(card(kind="deeper"))]
    tid = await new_thread(client)

    events = await turn(client, tid, action="ask", text="air conditioning")
    names = [e for e, _ in events]
    assert names.index("done") < names.index("translation") and "title" in names
    translations = [d for e, d in events if e == "translation"]
    assert [t["partial"] for t in translations] == [True, False]  # streamed, then complete
    assert translations[0]["zh"] == {"concept": "中:Air conditioning"}
    done = next(d for e, d in events if e == "done")
    zh = translations[-1]
    assert zh["message_id"] == done["message_id"]
    assert zh["zh"]["one_liner"] == "中:Air conditioning in one line."
    assert zh["zh"]["diagram_steps"][0] == {"label": "中:Evaporate indoors", "detail": "中:absorbs room heat"}
    assert zh["zh"]["branch_labels"] == ["中:Go deeper", "中:Heat pumps", "中:Refrigerants", "中:Something else"]
    assert zh["zh"]["captions"] == ["中:the four stages"]
    assert (await stored_card(session, done["message_id"]))["zh"] == zh["zh"]

    later = await turn(client, tid, action="dive")
    assert [e for e, _ in later][-1] == "translation" and "title" not in [e for e, _ in later]

    purposes = [r.purpose for r in (await session.scalars(select(ApiCall).order_by(ApiCall.id))).all()]
    assert purposes.count("translate") == 2


async def test_translation_failure_leaves_the_card_in_english(client, session, llm, light):
    light.replies += [RuntimeError("haiku down"), {"title": "T"}]
    llm.scripts.append(Script.of(card()))
    tid = await new_thread(client)
    events = await turn(client, tid, action="ask", text="hi")
    assert [e for e, _ in events][-2:] == ["done", "title"]
    done = next(d for e, d in events if e == "done")
    assert "zh" not in await stored_card(session, done["message_id"])


async def test_translation_can_be_switched_off(client, llm, light, monkeypatch):
    monkeypatch.setattr(get_settings(), "translate_cards", False)
    llm.scripts.append(Script.of(card()))
    tid = await new_thread(client)
    events = await turn(client, tid, action="ask", text="hi")
    assert "translation" not in [e for e, _ in events]
    assert all("branch_labels" not in c["schema"]["properties"] for c in light.calls)


async def test_on_demand_translation_for_old_cards(client, session, light):
    tid = await new_thread(client)
    msg = Message(thread_id=uuid.UUID(tid), seq=1, role="assistant", content="{}", card=card())
    session.add(msg)
    await session.commit()

    res = await client.post(f"/api/messages/{msg.id}/translate")
    assert res.status_code == 200
    assert res.json()["zh"]["concept"] == "中:Air conditioning"
    assert (await stored_card(session, str(msg.id)))["zh"]["concept"] == "中:Air conditioning"

    again = await client.post(f"/api/messages/{msg.id}/translate")  # already stored: no new call
    assert again.json()["zh"]["concept"] == "中:Air conditioning"
    assert len(light.calls) == 1


async def test_translate_endpoint_rejects_non_cards(client, session, light):
    tid = await new_thread(client)
    user_msg = Message(thread_id=uuid.UUID(tid), seq=1, role="user", content="hi")
    session.add(user_msg)
    await session.commit()
    assert (await client.post(f"/api/messages/{user_msg.id}/translate")).status_code == 404
    assert (await client.post(f"/api/messages/{uuid.uuid4()}/translate")).status_code == 404


async def test_lists_are_fitted_to_the_english_lengths():
    fake = FakeLightLLM(
        replies=[
            {
                "concept": "空调",
                "one_liner": "",
                "example": "",
                "diagram_title": "",
                "diagram_steps": [],  # model dropped the steps
                "highlights": ["一", "二", "三", "四"],  # and added a highlight
                "bridge": "",
                "body_md": "",
                "captions": [],
                "branch_labels": ["深入"],
            }
        ]
    )
    zh, _ = await translate.translate_card(fake, {**card(), "images": [{"caption": "c"}]})
    assert zh["highlights"] == ["一", "二", "三"]
    assert len(zh["diagram_steps"]) == 4 and zh["diagram_steps"][0] == {"label": "", "detail": ""}
    assert zh["captions"] == [""]
    assert zh["branch_labels"] == ["深入", "", "", ""]


@pytest.mark.parametrize("field", ["concept", "body_md", "diagram_steps", "branch_labels"])
def test_payload_covers_every_text_field(field):
    assert field in translate.payload(card())
