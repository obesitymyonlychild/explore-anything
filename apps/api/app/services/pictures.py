"""Turn the card's Wikipedia article titles into real images, via Wikipedia's free REST API.

Claude never writes image URLs (they'd often be wrong); it names articles whose lead image shows the
concept, and this module asks Wikipedia for that article's thumbnail. Titles that don't resolve, are
disambiguation pages, or have no image are dropped. No API cost; results are cached in memory.
"""

import asyncio
import logging
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
# Wikimedia asks API clients to identify themselves.
HEADERS = {"User-Agent": "ExploreAnything/0.1 (personal, non-commercial learning app)", "Accept": "application/json"}
TIMEOUT = 4.0
MAX_PICTURES = 2
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}  # Wikimedia throttles bursts with 403/429
RETRY_DELAY = 0.6

_cache: dict[str, dict | None] = {}


async def _lookup(client: httpx.AsyncClient, title: str) -> dict | None:
    key = title.strip().casefold()
    if key in _cache:
        return _cache[key]
    url = SUMMARY_URL.format(quote(title.strip().replace(" ", "_"), safe=""))
    try:
        res = await client.get(url)
        if res.status_code in RETRY_STATUSES:
            await asyncio.sleep(RETRY_DELAY)
            res = await client.get(url)
    except httpx.HTTPError as e:
        log.info("wikipedia lookup failed for %r: %s", title, e)
        return None  # not cached: may be a transient network problem
    if res.status_code not in (200, 404):
        log.info("wikipedia lookup for %r returned %s; not caching", title, res.status_code)
        return None
    data = res.json() if res.status_code == 200 else {}
    thumb = (data.get("thumbnail") or {}).get("source")
    found = None
    if data.get("type") == "standard" and thumb:
        found = {
            "title": data.get("title", title),
            "thumb_url": thumb,
            "page_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        }
    _cache[key] = found
    return found


async def resolve(pictures: list[dict], client: httpx.AsyncClient | None = None) -> list[dict]:
    """[{wikipedia_title, caption}] -> [{title, caption, thumb_url, page_url}], duplicates dropped."""
    wanted = [p for p in pictures if p.get("wikipedia_title", "").strip()][:MAX_PICTURES]
    if not wanted:
        return []
    own = client is None
    client = client or httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
    try:
        found = await asyncio.gather(*(_lookup(client, p["wikipedia_title"]) for p in wanted))
    finally:
        if own:
            await client.aclose()
    images, seen = [], set()
    for pic, hit in zip(wanted, found, strict=True):
        if hit and hit["thumb_url"] not in seen:
            seen.add(hit["thumb_url"])
            images.append({**hit, "caption": pic.get("caption", "")})
    return images
