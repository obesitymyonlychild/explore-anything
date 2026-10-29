"""Optional password gate for serving the app on a home network.

Set APP_PASSWORD in .env and every page and API call needs a session cookie, which /login hands out.
The cookie is an HMAC of a fixed message keyed by the password, so changing the password signs
everyone out and there is no session table. Unset (the default), the app stays open, as on localhost.
"""

import asyncio
import hashlib
import hmac
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from app.settings import get_settings

COOKIE = "ea_session"
COOKIE_MAX_AGE = 365 * 24 * 3600
WRONG_PASSWORD_DELAY = 1.0  # seconds; slows down guessing
# Reachable without a session: the login page itself, and what a phone fetches to install the app.
OPEN_PATHS = ("/login", "/manifest.webmanifest", "/static/icons/")
LOGIN_PAGE = Path(__file__).parent / "static" / "login.html"

router = APIRouter(include_in_schema=False)


def session_token(password: str) -> str:
    return hmac.new(password.encode(), b"explore-anything-session", hashlib.sha256).hexdigest()


def is_signed_in(request: Request, password: str) -> bool:
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), session_token(password))


async def require_password(request: Request, call_next):
    password = get_settings().app_password
    path = request.url.path
    if not password or path.startswith(OPEN_PATHS) or is_signed_in(request, password):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@router.get("/login")
async def login_page() -> FileResponse:
    return FileResponse(LOGIN_PAGE, headers={"Cache-Control": "no-cache"})


@router.post("/login")
async def login(request: Request) -> Response:
    password = get_settings().app_password
    given = parse_qs((await request.body()).decode()).get("password", [""])[0]
    if not password:
        return RedirectResponse("/", status_code=303)
    if not hmac.compare_digest(given.encode(), password.encode()):
        await asyncio.sleep(WRONG_PASSWORD_DELAY)
        return RedirectResponse("/login?wrong=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, session_token(password), max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
    return response
