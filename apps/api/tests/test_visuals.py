import json

import httpx
import pytest

from app.services import pictures
from tests.fake_llm import Script, card
from tests.test_turns import new_thread, turn


@pytest.fixture
def real_resolve(monkeypatch):
    """Undo the autouse fake and clear the cache, so the real resolver runs (against a mock transport)."""
    monkeypatch.undo()
    pictures._cache.clear()
    yield pictures.resolve
    pictures._cache.clear()


def wiki_client(pages: dict[str, dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.path.rsplit("/", 1)[-1]
        if title not in pages:
            return httpx.Response(404, json={"type": "not_found"})
        return httpx.Response(200, json=pages[title])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


PAGE = {
    "type": "standard",
    "title": "Heat pump",
    "thumbnail": {"source": "https://upload.wikimedia.org/heat_pump.png"},
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Heat_pump"}},
}


async def test_resolve_keeps_only_real_images(real_resolve):
    client = wiki_client(
        {
            "Heat_pump": PAGE,
            "Mercury": {"type": "disambiguation", "title": "Mercury"},
            "Entropy": {"type": "standard", "title": "Entropy"},  # no image
        }
    )
    images = await real_resolve(
        [
            {"wikipedia_title": "Heat pump", "caption": "outdoor unit"},
            {"wikipedia_title": "Mercury", "caption": "x"},
        ],
        client,
    )
    assert images == [
        {
            "title": "Heat pump",
            "thumb_url": "https://upload.wikimedia.org/heat_pump.png",
            "page_url": "https://en.wikipedia.org/wiki/Heat_pump",
            "caption": "outdoor unit",
        }
    ]
    assert await real_resolve([{"wikipedia_title": "Entropy", "caption": ""}], client) == []
    assert await real_resolve([{"wikipedia_title": "Nope", "caption": ""}], client) == []


async def test_resolve_caps_and_dedupes(real_resolve):
    client = wiki_client({"Heat_pump": PAGE, "Heat_pumps": PAGE})
    pics = [{"wikipedia_title": t, "caption": ""} for t in ("Heat pump", "Heat pumps", "Third", "Fourth")]
    images = await real_resolve(pics, client)
    assert len(images) == 1  # two titles, same image; the rest are past MAX_PICTURES or missing


async def test_network_errors_mean_no_picture(real_resolve):
    def boom(request):
        raise httpx.ConnectError("offline")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    assert await real_resolve([{"wikipedia_title": "Heat pump", "caption": ""}], client) == []
    assert "heat pump" not in pictures._cache  # transient failures aren't cached


async def test_one_step_diagram_is_dropped(client, llm):
    bad = card(diagram={"kind": "flow", "title": "x", "steps": [{"label": "only one", "detail": ""}]})
    llm.scripts.append(Script(json.dumps(bad)))
    tid = await new_thread(client)
    events = await turn(client, tid, action="ask", text="hi")
    done = next(d for e, d in events if e == "done")
    assert done["card"]["diagram"] == {"kind": "none", "title": "x", "steps": []}


async def test_throttling_is_retried_and_never_cached(real_resolve, monkeypatch):
    monkeypatch.setattr(pictures, "RETRY_DELAY", 0)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) <= 2:  # first lookup: throttled twice in a row
            return httpx.Response(403, text="<html>Wikimedia Error</html>")
        return httpx.Response(200, json=PAGE)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    pic = [{"wikipedia_title": "Heat pump", "caption": ""}]
    assert await real_resolve(pic, client) == []
    assert "heat pump" not in pictures._cache
    assert len(await real_resolve(pic, client)) == 1  # the next card gets the picture
    assert len(calls) == 3
