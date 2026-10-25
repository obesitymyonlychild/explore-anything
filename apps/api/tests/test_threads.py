import uuid

from sqlalchemy import select

from app.models import InterestEvent, Message
from app.settings import DEFAULT_USER_ID


async def test_create_and_list_threads_newest_first(client):
    first = (await client.post("/api/threads", json={"title": "Tides"})).json()
    second = (await client.post("/api/threads", json={})).json()
    assert first["depth"] == "explain"
    assert second["title"] is None

    listed = (await client.get("/api/threads")).json()
    assert [t["id"] for t in listed] == [second["id"], first["id"]]


async def test_get_thread_includes_messages_in_order(client, session):
    thread = (await client.post("/api/threads", json={})).json()
    tid = uuid.UUID(thread["id"])
    session.add_all(
        [
            Message(thread_id=tid, seq=2, role="assistant", content="{}", card={"concept": "Tides"}),
            Message(thread_id=tid, seq=1, role="user", action="ask", content="why are there tides?"),
        ]
    )
    await session.commit()

    detail = (await client.get(f"/api/threads/{tid}")).json()
    assert [m["seq"] for m in detail["messages"]] == [1, 2]
    assert detail["messages"][1]["card"] == {"concept": "Tides"}


async def test_archive_hides_thread_from_default_list(client):
    thread = (await client.post("/api/threads", json={})).json()
    await client.patch(f"/api/threads/{thread['id']}", json={"archived": True})
    assert (await client.get("/api/threads")).json() == []
    assert len((await client.get("/api/threads?archived=true")).json()) == 1


async def test_depth_change_is_validated_and_logged(client, session):
    thread = (await client.post("/api/threads", json={})).json()

    bad = await client.patch(f"/api/threads/{thread['id']}", json={"depth": "deep"})
    assert bad.status_code == 422

    res = await client.patch(f"/api/threads/{thread['id']}", json={"depth": "mechanism"})
    assert res.json()["depth"] == "mechanism"
    events = (await session.scalars(select(InterestEvent))).all()
    assert [(e.action, e.meta) for e in events] == [("depth_set", {"from": "explain", "to": "mechanism"})]
    assert events[0].user_id == DEFAULT_USER_ID


async def test_unknown_thread_is_404(client):
    res = await client.get(f"/api/threads/{uuid.uuid4()}")
    assert res.status_code == 404
