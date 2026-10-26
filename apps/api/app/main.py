from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import concepts, health, links, spark, takeaways, threads, turns, usage

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Explore Anything")


@app.middleware("http")
async def revalidate_page_assets(request: Request, call_next):
    # The page has no build step / hashed filenames, so make browsers revalidate (ETag) on every load.
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


for module in (health, usage, threads, turns, spark, concepts, links, takeaways):
    app.include_router(module.router, prefix="/api")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
