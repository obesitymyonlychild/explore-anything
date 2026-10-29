import pytest

from app import auth
from app.settings import get_settings


@pytest.fixture
def password(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_password", "hunter2")
    monkeypatch.setattr(auth, "WRONG_PASSWORD_DELAY", 0)
    return "hunter2"


async def test_open_without_a_password(client):
    assert (await client.get("/api/threads")).status_code == 200
    assert (await client.get("/")).status_code == 200


async def test_everything_needs_a_session_when_a_password_is_set(client, password):
    assert (await client.get("/api/threads")).status_code == 401
    page = await client.get("/")
    assert (page.status_code, page.headers["location"]) == (303, "/login")
    # The login page and what a phone needs to install the app stay reachable.
    assert (await client.get("/login")).status_code == 200
    assert (await client.get("/manifest.webmanifest")).status_code == 200
    assert (await client.get("/static/icons/icon.svg")).status_code == 200


async def test_login(client, password):
    wrong = await client.post("/login", data={"password": "nope"})
    assert (wrong.status_code, wrong.headers["location"]) == (303, "/login?wrong=1")
    assert auth.COOKIE not in wrong.cookies

    right = await client.post("/login", data={"password": password})
    assert (right.status_code, right.headers["location"]) == (303, "/")
    client.cookies.set(auth.COOKIE, right.cookies[auth.COOKIE])
    assert (await client.get("/api/threads")).status_code == 200

    get_settings().app_password = "changed"  # a new password signs everyone out
    assert (await client.get("/api/threads")).status_code == 401
