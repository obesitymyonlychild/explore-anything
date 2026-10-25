from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db import engine
from app.models import Base


async def test_migrations_match_models():
    async with engine.connect() as conn:
        diff = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    assert diff == []


async def test_health(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["db"] is True


async def test_index_page_served(client):
    res = await client.get("/")
    assert res.status_code == 200
    assert "Explore Anything" in res.text
    assert res.headers["cache-control"] == "no-cache"
    assert (await client.get("/static/app.js")).headers["cache-control"] == "no-cache"
    assert "cache-control" not in (await client.get("/api/health")).headers
