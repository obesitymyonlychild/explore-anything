from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import concepts, health, links, takeaways, threads

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Explore Anything")

for module in (health, threads, concepts, links, takeaways):
    app.include_router(module.router, prefix="/api")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
