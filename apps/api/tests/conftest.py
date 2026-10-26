import asyncio
import os
from pathlib import Path

import pytest

from app.settings import Settings

# Point the app at the test database before app.db creates its engine, and make sure no test can
# ever reach the real Anthropic API with the key from .env (env vars override .env).
TEST_DB_URL = Settings().test_database_url
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"

import asyncpg  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.llm.client import get_llm  # noqa: E402
from app.llm.light import get_light_llm  # noqa: E402
from app.main import app  # noqa: E402
from app.services import orchestrator  # noqa: E402
from tests.fake_llm import FakeLightLLM, FakeLLM  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]
DATA_TABLES = "thread, message, concept, concept_link, takeaway, takeaway_concept, interest_event, api_call"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Fresh schema for the test run, built by the real migrations."""

    async def reset_schema():
        conn = await asyncpg.connect(TEST_DB_URL.replace("+asyncpg", ""))
        try:
            await conn.execute("drop schema public cascade; create schema public;")
        finally:
            await conn.close()

    asyncio.run(reset_schema())
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DB_URL
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
async def clean_tables():
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"truncate {DATA_TABLES} restart identity cascade"))


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s


@pytest.fixture
def light():
    fake = FakeLightLLM()
    app.dependency_overrides[get_light_llm] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_light_llm, None)


@pytest.fixture
def llm(monkeypatch, light):
    fake = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: fake
    monkeypatch.setattr(orchestrator, "EMIT_INTERVAL", 0)  # emit every partial
    yield fake
    app.dependency_overrides.pop(get_llm, None)
