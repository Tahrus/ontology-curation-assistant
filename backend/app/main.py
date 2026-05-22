from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.config import get_settings


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Human-in-the-loop AI-assisted ontology curation workflow.",
)

app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}

