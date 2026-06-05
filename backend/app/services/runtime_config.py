from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.literature.pipeline import LiteraturePipelineConfig
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


@dataclass(frozen=True)
class LiteratureRuntimeConfig:
    zotero_literature_storage_path: Path | None
    base_dir: Path
    pdf_dir: Path
    generated_md_dir: Path
    papers_dir: Path
    combined_output_file: Path
    fuzzy_min_score: float


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


def literature_config(session: Session) -> LiteratureRuntimeConfig:
    settings = get_settings()
    storage_value = (
        get_runtime_value(session, "zotero_literature_storage_path")
        or settings.zotero_literature_storage_path
    )
    return LiteratureRuntimeConfig(
        zotero_literature_storage_path=Path(storage_value) if storage_value else None,
        base_dir=Path(get_runtime_value(session, "literature_base_dir") or settings.literature_base_dir),
        pdf_dir=Path(get_runtime_value(session, "literature_pdf_dir") or settings.literature_pdf_dir),
        generated_md_dir=Path(
            get_runtime_value(session, "literature_generated_md_dir")
            or settings.literature_generated_md_dir
        ),
        papers_dir=Path(
            get_runtime_value(session, "literature_repository_path")
            or settings.literature_repository_path
        ),
        combined_output_file=Path(
            get_runtime_value(session, "literature_combined_output_file")
            or settings.literature_combined_output_file
        ),
        fuzzy_min_score=float(
            get_runtime_value(session, "literature_fuzzy_min_score")
            or settings.literature_fuzzy_min_score
        ),
    )


def literature_pipeline_config(session: Session) -> LiteraturePipelineConfig:
    config = literature_config(session)
    return LiteraturePipelineConfig(
        zotero_literature_storage_path=config.zotero_literature_storage_path,
        base_dir=config.base_dir,
        pdf_dir=config.pdf_dir,
        generated_md_dir=config.generated_md_dir,
        papers_dir=config.papers_dir,
        combined_output_file=config.combined_output_file,
        fuzzy_min_score=config.fuzzy_min_score,
    )


def config_status(session: Session) -> dict[str, object]:
    zotero = zotero_config(session)
    llm = llm_config(session)
    literature = literature_config(session)
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
            "ppo_odk_ontology_path": str(settings.ppo_odk_ontology_path),
            "ppo_odk_ontology_path_exists": settings.ppo_odk_ontology_path.exists(),
        },
        "ontology": {
            "path": get_runtime_value(session, "local_ontology_path")
            or str(settings.local_ontology_path),
            "selected_file": get_runtime_value(session, "local_ontology_file"),
        },
        "literature": {
            "zotero_literature_storage_path": (
                str(literature.zotero_literature_storage_path)
                if literature.zotero_literature_storage_path
                else None
            ),
            "zotero_literature_storage_path_exists": (
                literature.zotero_literature_storage_path.exists()
                if literature.zotero_literature_storage_path
                else False
            ),
            "base_dir": str(literature.base_dir),
            "pdf_dir": str(literature.pdf_dir),
            "generated_md_dir": str(literature.generated_md_dir),
            "papers_dir": str(literature.papers_dir),
            "combined_output_file": str(literature.combined_output_file),
            "combined_output_exists": literature.combined_output_file.exists(),
            "fuzzy_min_score": literature.fuzzy_min_score,
        },
    }
