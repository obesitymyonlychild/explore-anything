import uuid

import pytest

from app.services.concepts import get_or_create, slugify
from app.settings import DEFAULT_USER_ID


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Heat Pump", "heat-pump"),
        ("  heat   pump! ", "heat-pump"),
        ("Vapor-compression refrigeration cycle", "vapor-compression-refrigeration-cycle"),
        ("C++", "c++"),
        ("Café", "café"),
    ],
)
def test_slugify(name, slug):
    assert slugify(name) == slug


async def concept(client, name):
    res = await client.post("/api/concepts", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()


async def test_create_concept_dedupes_by_slug(client):
    a = await concept(client, "Heat Pump")
    b = await concept(client, "heat  pump!")
    assert a["id"] == b["id"]
    assert a["name"] == "Heat Pump"
    assert a["explored"] is False


async def test_blank_concept_name_rejected(client):
    assert (await client.post("/api/concepts", json={"name": "!!!"})).status_code == 422
    assert (await client.post("/api/concepts", json={"name": ""})).status_code == 422


async def test_get_or_create_marks_explored(session):
    c = await get_or_create(session, DEFAULT_USER_ID, "Tides")
    assert c.explored is False
    c = await get_or_create(session, DEFAULT_USER_ID, "tides", explored=True)
    assert c.explored is True
    c = await get_or_create(session, DEFAULT_USER_ID, "Tides")  # never flips back
    assert c.explored is True
    await session.commit()


async def test_search_puts_prefix_matches_first(client):
    for name in ["Air conditioning", "Heat pump", "Heat exchanger", "Latent heat", "Tides"]:
        await concept(client, name)

    names = [c["name"] for c in (await client.get("/api/concepts?q=heat")).json()]
    assert names == ["Heat exchanger", "Heat pump", "Latent heat"]

    all_names = [c["name"] for c in (await client.get("/api/concepts")).json()]
    assert all_names == sorted(all_names)
    assert (await client.get("/api/concepts?q=%25")).json() == []  # % is literal, not a wildcard


async def test_link_shows_on_both_concepts(client):
    ac = await concept(client, "Air conditioning")
    hp = await concept(client, "Heat pump")

    res = await client.post(
        "/api/links", json={"a_concept_id": ac["id"], "b_concept_id": hp["id"], "note": " same cycle, reversed "}
    )
    assert res.status_code == 201
    link = res.json()
    assert link["note"] == "same cycle, reversed"
    assert {link["a"]["name"], link["b"]["name"]} == {"Air conditioning", "Heat pump"}

    ac_detail = (await client.get(f"/api/concepts/{ac['id']}")).json()
    hp_detail = (await client.get(f"/api/concepts/{hp['id']}")).json()
    assert [lc["concept"]["name"] for lc in ac_detail["links"]] == ["Heat pump"]
    assert [lc["concept"]["name"] for lc in hp_detail["links"]] == ["Air conditioning"]
    assert ac_detail["links"][0]["note"] == "same cycle, reversed"


async def test_link_rules(client):
    ac = await concept(client, "Air conditioning")
    hp = await concept(client, "Heat pump")

    self_link = await client.post("/api/links", json={"a_concept_id": ac["id"], "b_concept_id": ac["id"]})
    assert self_link.status_code == 422

    await client.post("/api/links", json={"a_concept_id": ac["id"], "b_concept_id": hp["id"]})
    reverse = await client.post("/api/links", json={"a_concept_id": hp["id"], "b_concept_id": ac["id"]})
    assert reverse.status_code == 409  # undirected: same pair

    missing = await client.post("/api/links", json={"a_concept_id": ac["id"], "b_concept_id": str(uuid.uuid4())})
    assert missing.status_code == 404


async def test_update_and_delete_link(client):
    ac = await concept(client, "Air conditioning")
    hp = await concept(client, "Heat pump")
    link = (await client.post("/api/links", json={"a_concept_id": ac["id"], "b_concept_id": hp["id"]})).json()

    updated = await client.patch(f"/api/links/{link['id']}", json={"note": "both move heat uphill"})
    assert updated.json()["note"] == "both move heat uphill"

    assert (await client.delete(f"/api/links/{link['id']}")).status_code == 204
    assert (await client.get(f"/api/concepts/{ac['id']}")).json()["links"] == []
