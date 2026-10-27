import json
import uuid

import anthropic
import httpx2
import pytest
from sqlalchemy import select

from app.models import Concept, InterestEvent, Message, Thread
from app.settings import get_settings
from tests.fake_llm import THINKING, Script, card


def done(events) -> dict:
    return next(d for e, d in events if e == "done")


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def turn(client, thread_id, **body) -> list[tuple[str, dict]]:
    res = await client.post(f"/api/threads/{thread_id}/turns", json=body)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    return parse_sse(res.text)


async def new_thread(client) -> str:
    return (await client.post("/api/threads", json={})).json()["id"]


async def messages(session, thread_id) -> list[Message]:
    return (
        await session.scalars(select(Message).where(Message.thread_id == uuid.UUID(thread_id)).order_by(Message.seq))
    ).all()


async def test_ask_streams_a_card_and_stores_everything(client, session, llm):
    llm.scripts.append(Script.of(card()))
    tid = await new_thread(client)

    events = await turn(client, tid, action="ask", text="how does air conditioning work?")
    names = [e for e, _ in events]
    assert names[:2] == ["meta", "status"] and "done" in names and names[-1] in ("translation", "title")
    assert events[1][1] == {"state": "thinking"}
    partials = [d for e, d in events if e == "card"]
    assert len(partials) > 3
    assert partials[0].keys() <= partials[-1].keys()  # fields fill in over time

    finished = done(events)
    assert finished["card"]["concept"] == "Air conditioning"
    assert finished["card"]["diagram"]["kind"] == "cycle"
    assert finished["card"]["images"] == [
        {
            "title": "Vapor-compression refrigeration",
            "caption": "the four stages",
            "thumb_url": "https://img/x.png",
            "page_url": "https://wiki/x",
        }
    ]
    assert finished["usage"]["output_tokens"] == 50

    user, assistant = await messages(session, tid)
    assert (user.role, user.action, user.content) == ("user", "ask", "how does air conditioning work?")
    assert '<turn action="ask" depth="explain"/>' in user.api_content[0]["text"]
    assert {k: v for k, v in assistant.card.items() if k != "zh"} == finished["card"]  # zh arrives after done
    assert assistant.api_content[0] == THINKING  # stored verbatim for replay
    assert str(assistant.id) == finished["message_id"]

    thread = await session.get(Thread, uuid.UUID(tid))
    concept = await session.get(Concept, thread.current_concept_id)
    assert concept.name == "Air conditioning" and concept.explored
    assert thread.root_concept_id == concept.id
    assert thread.title == "Generated title"
    assert str(concept.id) == finished["concept_id"]

    events_logged = (await session.scalars(select(InterestEvent))).all()
    assert [e.action for e in events_logged] == ["ask"]


async def test_dive_raises_depth_and_replays_history_verbatim(client, session, llm):
    llm.scripts += [Script.of(card()), Script.of(card(kind="deeper", depth="explain"))]
    tid = await new_thread(client)
    await turn(client, tid, action="ask", text="air conditioning")

    events = await turn(client, tid, action="dive")
    assert events[0][1]["depth"] == "mechanism"
    assert done(events)["card"]["depth"] == "mechanism"  # server's depth wins over the model's

    sent = llm.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    stored = await messages(session, tid)
    assert sent[1]["content"] == stored[1].api_content  # thinking block included, unchanged
    assert sent[0]["content"] == llm.calls[0]["messages"][0]["content"]  # earlier turns never change
    assert '<turn action="dive" depth="mechanism" focus="Air conditioning"/>' in sent[2]["content"][0]["text"]
    assert stored[2].content == "Go deeper."

    thread = await session.get(Thread, uuid.UUID(tid))
    assert thread.depth == "mechanism"


async def test_dive_caps_at_expert_and_explicit_depth(client, llm):
    llm.scripts += [Script.of(card()), Script.of(card()), Script.of(card())]
    tid = await new_thread(client)
    await turn(client, tid, action="ask", text="air conditioning", depth="expert")
    events = await turn(client, tid, action="dive")
    assert events[0][1]["depth"] == "expert"
    events = await turn(client, tid, action="dive", depth="glance")
    assert events[0][1]["depth"] == "glance"


async def test_users_notes_reach_the_prompt(client, llm):
    llm.scripts += [Script.of(card()), Script.of(card(kind="deeper"))]
    tid = await new_thread(client)
    ac_id = done(await turn(client, tid, action="ask", text="air conditioning"))["concept_id"]

    hp = (await client.post("/api/concepts", json={"name": "Heat pump"})).json()
    await client.post("/api/links", json={"a_concept_id": ac_id, "b_concept_id": hp["id"], "note": "same cycle"})
    await client.post(
        "/api/takeaways", json={"kind": "idea", "body": "predictive maintenance?", "concept_ids": [ac_id]}
    )

    await turn(client, tid, action="dive")
    prompt = llm.calls[1]["messages"][-1]["content"][0]["text"]
    assert '<my_notes concept="Air conditioning">' in prompt
    assert "- Heat pump: same cycle" in prompt
    assert "- [idea] predictive maintenance?" in prompt


async def test_branch_moves_focus_to_the_new_concept(client, session, llm):
    llm.scripts += [Script.of(card()), Script.of(card("Heat pump"))]
    tid = await new_thread(client)
    await turn(client, tid, action="ask", text="air conditioning")

    events = await turn(client, tid, action="branch", concept="Heat pump")
    assert done(events)["card"]["concept"] == "Heat pump"
    assert 'focus="Heat pump"' in llm.calls[1]["messages"][-1]["content"][0]["text"]
    stored = await messages(session, tid)
    assert stored[2].content == "Related: Heat pump"

    thread = await session.get(Thread, uuid.UUID(tid))
    assert (await session.get(Concept, thread.current_concept_id)).name == "Heat pump"
    assert (await session.get(Concept, thread.root_concept_id)).name == "Air conditioning"


async def test_ask_with_a_saved_question(client, session, llm):
    llm.scripts += [Script.of(card()), Script.of(card(kind="answer", body_md="Yes: ..."))]
    tid = await new_thread(client)
    ac_id = done(await turn(client, tid, action="ask", text="air conditioning"))["concept_id"]
    q = (
        await client.post(
            "/api/takeaways", json={"kind": "question", "body": "Does this exist?", "concept_ids": [ac_id]}
        )
    ).json()

    await turn(client, tid, action="ask", takeaway_id=q["id"])
    prompt = llm.calls[1]["messages"][-1]["content"][0]["text"]
    assert "<message>\nDoes this exist?\n</message>" in prompt
    assert 'focus="Air conditioning"' in prompt
    assert "- [question] Does this exist?" in prompt


async def test_refusal_keeps_no_reply_and_the_retry_replaces_the_turn(client, session, llm):
    llm.scripts += [Script("", stop_reason="refusal"), Script.of(card())]
    tid = await new_thread(client)

    events = await turn(client, tid, action="ask", text="first try")
    assert events[-1] == ("error", {"code": "refusal", "message": events[-1][1]["message"]})
    assert [m.role for m in await messages(session, tid)] == ["user"]

    await turn(client, tid, action="ask", text="second try")
    stored = await messages(session, tid)
    assert [(m.seq, m.role) for m in stored] == [(1, "user"), (2, "assistant")]
    assert stored[0].content == "second try"
    assert [m["role"] for m in llm.calls[1]["messages"]] == ["user"]


@pytest.mark.parametrize(
    ("script", "code"),
    [
        (Script('{"concept": "X"}'), "invalid_card"),
        (Script.of(card(), stop_reason="max_tokens"), "max_tokens"),
        (Script("", raise_exc=anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))), "connection"),
        (Script("", raise_exc=RuntimeError("boom")), "internal"),
    ],
)
async def test_failures_become_error_events(client, session, llm, script, code):
    llm.scripts.append(script)
    tid = await new_thread(client)
    events = await turn(client, tid, action="ask", text="hi")
    assert events[-1][0] == "error" and events[-1][1]["code"] == code
    assert [m.role for m in await messages(session, tid)] == ["user"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"action": "ask"}, 422),
        ({"action": "ask", "text": "   "}, 422),
        ({"action": "dive"}, 422),  # nothing to go deeper on yet
        ({"action": "branch"}, 422),
        ({"action": "dive", "takeaway_id": str(uuid.uuid4())}, 422),
        ({"action": "ask", "takeaway_id": str(uuid.uuid4())}, 404),
        ({"action": "fly"}, 422),
    ],
)
async def test_invalid_turns_are_rejected(client, llm, body, status):
    tid = await new_thread(client)
    res = await client.post(f"/api/threads/{tid}/turns", json=body)
    assert res.status_code == status, res.text
    assert llm.calls == []


async def test_turn_on_unknown_thread_is_404(client, llm):
    res = await client.post(f"/api/threads/{uuid.uuid4()}/turns", json={"action": "ask", "text": "hi"})
    assert res.status_code == 404


async def test_title_only_after_the_first_card(client, session, llm, light):
    llm.scripts += [Script.of(card()), Script.of(card(kind="deeper"))]
    tid = await new_thread(client)
    first = await turn(client, tid, action="ask", text="how does AC work?")
    assert ("title", {"title": "Generated title"}) in first
    title_calls = [c for c in light.calls if "title" in c["schema"]["properties"]]
    assert "how does AC work?" in title_calls[0]["prompt"]

    second = await turn(client, tid, action="dive")
    assert "title" not in [e for e, _ in second]
    assert len([c for c in light.calls if "title" in c["schema"]["properties"]]) == 1


async def test_title_failure_keeps_the_provisional_title(client, session, llm, light, monkeypatch):
    monkeypatch.setattr(get_settings(), "translate_cards", False)  # so the one light call is the title
    light.replies.append(RuntimeError("haiku down"))
    llm.scripts.append(Script.of(card()))
    tid = await new_thread(client)
    events = await turn(client, tid, action="ask", text="air conditioning")
    assert [e for e, _ in events][-1] == "done"
    assert (await session.get(Thread, uuid.UUID(tid))).title == "Air conditioning"


async def test_spark_turn_logs_topic_area_and_angle(client, session, llm):
    llm.scripts.append(Script.of(card("Air traffic controller")))
    tid = await new_thread(client)
    question = "What does an air traffic controller's shift actually look like?"
    await turn(
        client,
        tid,
        action="spark",
        concept="Air traffic controller",
        text=question,
        topic_area="Aviation and airports",
        angle="day-in-the-life",
    )

    user_msg = (await messages(session, tid))[0]
    assert user_msg.content == f"Surprise me: {question}"
    prompt = user_msg.api_content[0]["text"]
    assert '<turn action="spark" depth="explain" focus="Air traffic controller" angle="day-in-the-life"/>' in prompt
    assert f"<message>\n{question}\n</message>" in prompt
    event = (await session.scalars(select(InterestEvent))).one()
    assert (event.action, event.meta["topic_area"], event.meta["angle"]) == (
        "spark_shown",
        "Aviation and airports",
        "day-in-the-life",
    )


async def test_angle_only_applies_to_spark_turns(client, session, llm):
    llm.scripts.append(Script.of(card()))
    tid = await new_thread(client)
    await turn(client, tid, action="ask", text="hi", angle="day-in-the-life")
    assert "angle=" not in (await messages(session, tid))[0].api_content[0]["text"]


async def test_auth_error_has_a_clear_message(client, llm):
    response = httpx2.Response(401, request=httpx2.Request("POST", "https://x"))
    llm.scripts.append(Script("", raise_exc=anthropic.AuthenticationError("bad key", response=response, body=None)))
    tid = await new_thread(client)
    events = await turn(client, tid, action="ask", text="hi")
    assert events[-1][1]["code"] == "auth"
    assert "ANTHROPIC_API_KEY" in events[-1][1]["message"]
