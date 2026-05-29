from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models.db import AppSetting


SECRET_KEYS = {"zotero_api_key", "llm_api_key"}


@dataclass(frozen=True)
class ZoteroRuntimeConfig:
    library_type: str | None
    library_id: str | None
    api_key: str | None
    collection_key: str | None
    base_url: str


@dataclass(frozen=True)
class LlmRuntimeConfig:
    provider: str | None
    api_key: str | None
    model: str | None
    base_url: str | None


def get_runtime_value(session: Session, key: str) -> str | None:
    setting = session.get(AppSetting, key)
    if setting is not None:
        return setting.value

    settings = get_settings()
    return getattr(settings, key, None)


def set_runtime_values(session: Session, values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if value is None:
            continue
        setting = session.get(AppSetting, key)
        if setting is None:
            session.add(AppSetting(key=key, value=value))
        else:
            setting.value = value
    session.commit()


def mask_secret(value: str | None) -> str:
    return "configured" if value else "missing"


def display_value(key: str, value: str | None) -> str | None:
    if key in SECRET_KEYS:
        return mask_secret(value)
    return value


def zotero_config(session: Session) -> ZoteroRuntimeConfig:
    settings = get_settings()
    return ZoteroRuntimeConfig(
        library_type=get_runtime_value(session, "zotero_library_type"),
        library_id=get_runtime_value(session, "zotero_library_id"),
        api_key=get_runtime_value(session, "zotero_api_key"),
        collection_key=get_runtime_value(session, "zotero_collection_key"),
        base_url=get_runtime_value(session, "zotero_api_base_url") or settings.zotero_api_base_url,
    )


def llm_config(session: Session) -> LlmRuntimeConfig:
    return LlmRuntimeConfig(
        provider=get_runtime_value(session, "llm_provider"),
        api_key=get_runtime_value(session, "llm_api_key"),
        model=get_runtime_value(session, "llm_model"),
        base_url=get_runtime_value(session, "llm_base_url"),
    )


def config_status(session: Session) -> dict[str, object]:
    zotero = zotero_config(session)
    llm = llm_config(session)
    settings = get_settings()
    return {
        "backend": {"ok": True, "app_name": settings.app_name},
        "database": {"ok": True},
        "zotero": {
            "configured": bool(zotero.library_type and zotero.library_id),
            "has_api_key": bool(zotero.api_key),
            "library_type": zotero.library_type,
            "library_id": zotero.library_id,
            "collection_key": zotero.collection_key,
            "base_url": zotero.base_url,
            "api_key": mask_secret(zotero.api_key),
        },
        "llm": {
            "configured": bool(llm.provider and llm.api_key),
            "provider": llm.provider,
            "model": llm.model,
            "base_url": llm.base_url,
            "api_key": mask_secret(llm.api_key),
        },
        "odk": {
            "home": str(settings.odk_home),
            "home_exists": settings.odk_home.exists(),
            "ontology_repo": str(settings.ontology_repo) if settings.ontology_repo else None,
        },
        "ontology": {
            "path": get_runtime_value(session, "local_ontology_path")
            or str(settings.local_ontology_path),
            "selected_file": get_runtime_value(session, "local_ontology_file"),
        },
    }
