from fastapi import APIRouter

from backend.app.config import get_settings


router = APIRouter(prefix="/api")


@router.get("/config")
def read_config() -> dict[str, str | bool | None]:
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "odk_home": str(settings.odk_home),
        "odk_home_exists": settings.odk_home.exists(),
        "ontology_repo": str(settings.ontology_repo) if settings.ontology_repo else None,
        "require_human_approval": settings.require_human_approval,
    }

