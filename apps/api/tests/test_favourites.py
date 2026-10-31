import uuid

from sqlalchemy import select

from app.models import InterestEvent, Message


async def card_in_thread(client, session, concept="Tides", seq=2):
    thread = (await client.post("/api/threads", json={"title": "How tides work"})).json()
    msg = Message(
        thread_id=uuid.UUID(thread["id"]),
        seq=seq,
        role="assistant",
        content="{}",
        card={"concept": concept, "one_liner": f"{concept}, in one line."},
    )
    session.add(msg)
    await session.commit()
    return thread["id"], str(msg.id)


async def test_favourite_a_card_and_list_it(client, session):
    thread_id, message_id = await card_in_thread(client, session)

    assert (await client.put(f"/api/messages/{message_id}/favourite")).status_code == 204
    favs = (await client.get("/api/messages/favourites")).json()
    assert [(f["message_id"], f["thread_id"], f["thread_title"], f["concept"], f["one_liner"]) for f in favs] == [
        (message_id, thread_id, "How tides work", "Tides", "Tides, in one line.")
    ]
    # The thread shows the card as a favourite, so the page can draw the button as on.
    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert detail["messages"][0]["favourited_at"] == favs[0]["favourited_at"]

    events = (await session.scalars(select(InterestEvent).where(InterestEvent.action == "favourite"))).all()
    assert [str(e.thread_id) for e in events] == [thread_id]


async def test_favouriting_twice_keeps_one_entry_and_its_time(client, session):
    _, message_id = await card_in_thread(client, session)
    await client.put(f"/api/messages/{message_id}/favourite")
    first = (await client.get("/api/messages/favourites")).json()
    await client.put(f"/api/messages/{message_id}/favourite")
    assert (await client.get("/api/messages/favourites")).json() == first


async def test_newest_favourite_first(client, session):
    _, older = await card_in_thread(client, session, "Tides")
    _, newer = await card_in_thread(client, session, "Rainbows")
    await client.put(f"/api/messages/{older}/favourite")
    await client.put(f"/api/messages/{newer}/favourite")
    assert [f["concept"] for f in (await client.get("/api/messages/favourites")).json()] == ["Rainbows", "Tides"]


async def test_unfavourite(client, session):
    _, message_id = await card_in_thread(client, session)
    await client.put(f"/api/messages/{message_id}/favourite")
    assert (await client.delete(f"/api/messages/{message_id}/favourite")).status_code == 204
    assert (await client.get("/api/messages/favourites")).json() == []


async def test_only_cards_can_be_favourites(client, session):
    thread = (await client.post("/api/threads", json={})).json()
    question = Message(thread_id=uuid.UUID(thread["id"]), seq=1, role="user", content="why tides?")
    session.add(question)
    await session.commit()
    assert (await client.put(f"/api/messages/{question.id}/favourite")).status_code == 404
    assert (await client.put(f"/api/messages/{uuid.uuid4()}/favourite")).status_code == 404
