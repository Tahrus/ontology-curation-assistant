from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.config import get_settings
from backend.app.db.session import ensure_runtime_schema


settings = get_settings()
static_dir = Path(__file__).parent / "static"
images_dir = Path("Images")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_runtime_schema()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Human-in-the-loop AI-assisted ontology curation workflow.",
    lifespan=lifespan,
)

app.include_router(router)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
if images_dir.exists():
    app.mount("/assets", StaticFiles(directory=images_dir), name="assets")


@app.get("/", include_in_schema=False)
def browser_app() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/{page_name}", include_in_schema=False)
def browser_page(page_name: str) -> FileResponse:
    if page_name not in {"config", "zotero", "literature", "ontology", "curation", "export"}:
        return FileResponse(static_dir / "index.html", status_code=404)
    return FileResponse(static_dir / "index.html")
