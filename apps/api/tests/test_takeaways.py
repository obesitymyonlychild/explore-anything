import uuid

from sqlalchemy import select

from app.models import InterestEvent, Message


async def concept(client, name):
    return (await client.post("/api/concepts", json={"name": name})).json()


async def test_takeaway_attaches_to_several_concepts(client):
    ac = await concept(client, "Air conditioning")
    ad = await concept(client, "Anomaly detection")

    res = await client.post(
        "/api/takeaways",
        json={
            "kind": "idea",
            "body": "Could anomaly detection on compressor vibration cut energy use? Does it exist?",
            "concept_ids": [ac["id"], ad["id"]],
        },
    )
    assert res.status_code == 201
    tk = res.json()
    assert tk["kind"] == "idea"
    assert [c["name"] for c in tk["concepts"]] == ["Air conditioning", "Anomaly detection"]

    for c in (ac, ad):
        detail = (await client.get(f"/api/concepts/{c['id']}")).json()
        assert [t["id"] for t in detail["takeaways"]] == [tk["id"]]


async def test_takeaway_on_a_card_records_its_thread(client, session):
    ac = await concept(client, "Air conditioning")
    thread = (await client.post("/api/threads", json={})).json()
    msg = Message(thread_id=uuid.UUID(thread["id"]), seq=1, role="assistant", content="{}")
    session.add(msg)
    await session.commit()

    tk = (
        await client.post(
            "/api/takeaways",
            json={"body": "heat moves, cold isn't made", "concept_ids": [ac["id"]], "message_id": str(msg.id)},
        )
    ).json()
    assert tk["kind"] == "takeaway"
    assert tk["message_id"] == str(msg.id)
    assert tk["thread_id"] == thread["id"]

    events = (await session.scalars(select(InterestEvent))).all()
    assert [(e.action, str(e.thread_id)) for e in events] == [("takeaway", thread["id"])]


async def test_takeaway_validation(client):
    ac = await concept(client, "Air conditioning")
    no_concepts = await client.post("/api/takeaways", json={"body": "x", "concept_ids": []})
    assert no_concepts.status_code == 422
    bad_kind = await client.post("/api/takeaways", json={"body": "x", "kind": "rant", "concept_ids": [ac["id"]]})
    assert bad_kind.status_code == 422
    unknown = await client.post("/api/takeaways", json={"body": "x", "concept_ids": [str(uuid.uuid4())]})
    assert unknown.status_code == 404
    bad_msg = await client.post(
        "/api/takeaways", json={"body": "x", "concept_ids": [ac["id"]], "message_id": str(uuid.uuid4())}
    )
    assert bad_msg.status_code == 404


async def test_filter_update_delete(client):
    ac = await concept(client, "Air conditioning")
    hp = await concept(client, "Heat pump")
    q = (
        await client.post("/api/takeaways", json={"kind": "question", "body": "why R-32?", "concept_ids": [ac["id"]]})
    ).json()
    await client.post("/api/takeaways", json={"body": "noted", "concept_ids": [ac["id"]]})

    questions = (await client.get("/api/takeaways?kind=question")).json()
    assert [t["id"] for t in questions] == [q["id"]]
    assert len((await client.get(f"/api/takeaways?concept_id={ac['id']}")).json()) == 2

    updated = (await client.patch(f"/api/takeaways/{q['id']}", json={"concept_ids": [hp["id"]]})).json()
    assert [c["name"] for c in updated["concepts"]] == ["Heat pump"]
    assert updated["updated_at"] > q["updated_at"]
    assert len((await client.get(f"/api/takeaways?concept_id={ac['id']}")).json()) == 1

    assert (await client.delete(f"/api/takeaways/{q['id']}")).status_code == 204
    assert (await client.get(f"/api/takeaways?concept_id={hp['id']}")).json() == []
