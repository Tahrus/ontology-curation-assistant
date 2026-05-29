from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db.session import get_session
from backend.app.extraction.prompts import build_candidate_extraction_prompt
from backend.app.extraction.service import build_candidate_id, normalize_label, persist_candidates
from backend.app.llm.service import LlmUnavailableError, extract_candidates_with_optional_llm
from backend.app.models.core import ReviewStatus
from backend.app.models.db import AppSetting, CandidateTermRecord, LiteratureDocument, LiteratureSource
from backend.app.odk.integration import write_candidate_tsv, write_robot_template
from backend.app.ontology.local import (
    index_ontology_file,
    match_local_terms,
    scan_ontology_folder,
    search_terms,
)
from backend.app.ontology.ols import OlsLookupService
from backend.app.services.runtime_config import (
    config_status,
    display_value,
    llm_config,
    set_runtime_values,
    zotero_config,
)
from backend.app.zotero.client import ZoteroApiClient, ZoteroApiConfig, ZoteroApiError
from backend.app.zotero.importer import ParsedSource, import_parsed_sources, parse_source_item


router = APIRouter(prefix="/api")


class BrowserSetting(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str


class ZoteroConfigPayload(BaseModel):
    library_type: Literal["user", "group"]
    library_id: str = Field(min_length=1)
    api_key: str | None = None
    collection_key: str | None = None
    base_url: str | None = None


class LlmConfigPayload(BaseModel):
    provider: str = Field(min_length=1)
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class SavedApiConfigPayload(BaseModel):
    kind: Literal["zotero", "llm"]
    alias: str | None = None
    provider: str | None = None
    library_type: Literal["user", "group"] | None = None
    library_id: str | None = None
    api_key: str | None = None
    collection_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class RejectionPayload(BaseModel):
    reason: str | None = None


class ZoteroSyncPayload(BaseModel):
    collection_key: str | None = None
    limit: int | None = Field(default=None, ge=1, le=10000)


class OntologyPathPayload(BaseModel):
    path: str = Field(min_length=1)


class OntologyFilePayload(BaseModel):
    path: str = Field(min_length=1)


class LiteratureCreate(BaseModel):
    path: str | None = None
    filename: str | None = None
    content: str | None = None


class CandidateCreate(BaseModel):
    label: str = Field(min_length=1)
    document_id: int | None = None
    proposed_definition: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    proposed_parent: str | None = None
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    curator_rationale: str | None = None
    source_evidence: str | None = None
    mappings: list[str] = Field(default_factory=list)


class CandidateUpdate(BaseModel):
    label: str | None = None
    proposed_definition: str | None = None
    synonyms: list[str] | None = None
    proposed_parent: str | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[dict[str, Any]] | None = None
    review_status: ReviewStatus | None = None
    curator_rationale: str | None = None
    source_evidence: str | None = None
    mappings: list[str] | None = None
    selected_ols: dict[str, Any] | None = None
    selected_local: dict[str, Any] | None = None
    curator_decision: str | None = None


class ReviewAction(BaseModel):
    status: Literal["approved", "approved_with_edits", "rejected", "needs_more_evidence", "deferred"]
    rationale: str | None = None


class RefinementRequest(BaseModel):
    guidance: str = Field(min_length=1)
    document_id: int | None = None


class ExtractionRequest(BaseModel):
    document_id: int | None = None
    source_id: int | None = None
    guidance: str | None = None
    use_llm: bool = False


class OlsSelection(BaseModel):
    match: dict[str, Any] | None = None


class LocalSelection(BaseModel):
    match: dict[str, Any] | None = None


class CandidateDecisionPayload(BaseModel):
    decision: Literal[
        "use_existing_local_term",
        "use_existing_ols_term",
        "propose_new_term",
        "needs_review",
        "rejected",
    ]


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _candidate_payload(candidate: CandidateTermRecord) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "candidate_id": candidate.candidate_id,
        "document_id": candidate.document_id,
        "label": candidate.label,
        "proposed_definition": candidate.proposed_definition,
        "synonyms": _json_loads(candidate.synonyms_json, []),
        "proposed_parent": candidate.proposed_parent,
        "confidence_score": candidate.confidence_score,
        "review_status": candidate.review_status,
        "evidence": _json_loads(candidate.evidence_json, []),
        "curator_rationale": candidate.curator_rationale,
        "source_evidence": candidate.source_evidence,
        "mappings": _json_loads(candidate.mappings_json, []),
        "ols_matches": _json_loads(candidate.ols_matches_json, []),
        "selected_ols": _json_loads(candidate.selected_ols_json, None),
        "ols_lookup_status": candidate.ols_lookup_status,
        "local_matches": _json_loads(candidate.local_matches_json, []),
        "selected_local": _json_loads(candidate.selected_local_json, None),
        "local_lookup_status": candidate.local_lookup_status,
        "curator_decision": candidate.curator_decision,
        "refinement_guidance": candidate.refinement_guidance,
        "rejection_reason": candidate.rejection_reason,
        "permanently_rejected_at": (
            candidate.permanently_rejected_at.isoformat()
            if candidate.permanently_rejected_at
            else None
        ),
        "created_at": candidate.created_at.isoformat(),
    }


def _get_or_create_manual_document(session: Session) -> LiteratureDocument:
    document = session.scalar(
        select(LiteratureDocument).where(LiteratureDocument.path == "__manual_browser_candidates__")
    )
    if document is not None:
        return document

    document = LiteratureDocument(
        path="__manual_browser_candidates__",
        filename="Manual browser candidates",
        suffix=".manual",
        size_bytes=0,
        content="Candidates proposed manually from the browser UI.",
    )
    session.add(document)
    session.flush()
    return document


def _get_candidate(session: Session, candidate_id: int) -> CandidateTermRecord:
    candidate = session.get(CandidateTermRecord, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def _configured_ontology_path(session: Session) -> Path:
    settings = get_settings()
    setting = session.get(AppSetting, "local_ontology_path")
    return Path(setting.value if setting is not None else settings.local_ontology_path)


def _selected_ontology_file(session: Session) -> Path | None:
    setting = session.get(AppSetting, "local_ontology_file")
    return Path(setting.value) if setting is not None and setting.value else None


def _preferred_ontology_file(files: list[dict[str, Any]]) -> Path | None:
    if not files:
        return None
    preferred_names = [
        "ppo.owl",
        "ppo-edit.owl",
        "ppo-full.owl",
        "ppo-simple.owl",
        "ppo.obo",
        "ppo-full.obo",
    ]
    by_name = {Path(file["path"]).name.casefold(): file for file in files}
    for name in preferred_names:
        if name in by_name:
            return Path(by_name[name]["path"])
    return Path(files[0]["path"])


def _indexed_terms(session: Session):
    selected = _selected_ontology_file(session)
    if selected is None:
        scan = scan_ontology_folder(_configured_ontology_path(session))
        files = scan.get("files", [])
        selected = _preferred_ontology_file(files)
        if selected is None:
            return []
    return index_ontology_file(selected)


def _masked_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}-••••••••{value[-4:]}" if value.startswith("sk-") else f"••••••••{value[-4:]}"


def _saved_configs(session: Session) -> list[dict[str, Any]]:
    setting = session.get(AppSetting, "saved_api_configs_json")
    return _json_loads(setting.value if setting else None, [])


def _write_saved_configs(session: Session, configs: list[dict[str, Any]]) -> None:
    set_runtime_values(session, {"saved_api_configs_json": json.dumps(configs)})


def _public_saved_config(config: dict[str, Any], active_id: str | None) -> dict[str, Any]:
    public = {key: value for key, value in config.items() if key != "api_key"}
    public["api_key"] = _masked_secret(config.get("api_key"))
    public["active"] = config.get("id") == active_id
    return public


def _upsert_saved_config(
    session: Session,
    *,
    kind: Literal["zotero", "llm"],
    values: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    configs = _saved_configs(session)
    config = {
        "id": values.get("id") or str(uuid.uuid4()),
        "kind": kind,
        "alias": values.get("alias") or values.get("provider") or values.get("library_id") or kind,
        "provider": values.get("provider"),
        "library_type": values.get("library_type"),
        "library_id": values.get("library_id"),
        "collection_key": values.get("collection_key"),
        "model": values.get("model"),
        "base_url": values.get("base_url"),
        "api_key": values.get("api_key"),
        "created_at": values.get("created_at") or now,
        "updated_at": now,
    }
    configs = [item for item in configs if item.get("id") != config["id"]]
    configs.append(config)
    _write_saved_configs(session, configs)
    set_runtime_values(session, {f"active_{kind}_config_id": config["id"]})
    return config


def _active_config_id(session: Session, kind: str) -> str | None:
    setting = session.get(AppSetting, f"active_{kind}_config_id")
    return setting.value if setting else None


def _graph_from_terms(terms: list[Any], *, limit: int = 80) -> dict[str, Any]:
    visible_terms = terms[:limit]
    nodes = [
        {
            "id": term.term_id or term.iri,
            "label": term.label,
            "type": "ontology_term",
            "definition": term.definition,
            "iri": term.iri,
        }
        for term in visible_terms
    ]
    known_ids = {node["id"] for node in nodes}
    edges = []
    for term in visible_terms:
        child_id = term.term_id or term.iri
        for parent in term.parents or []:
            parent_id = str(parent)
            if parent_id not in known_ids:
                nodes.append({
                    "id": parent_id,
                    "label": parent_id,
                    "type": "parent_placeholder",
                    "definition": None,
                    "iri": parent_id,
                })
                known_ids.add(parent_id)
            edges.append({
                "id": f"{child_id}->{parent_id}",
                "source": child_id,
                "target": parent_id,
                "label": "subClassOf",
            })
    return {"nodes": nodes, "edges": edges}


def _document_from_source(session: Session, source: LiteratureSource) -> LiteratureDocument:
    path = f"__zotero_source__/{source.id}"
    document = session.scalar(select(LiteratureDocument).where(LiteratureDocument.path == path))
    if document is not None:
        return document

    creators = _json_loads(source.creators_json, [])
    creator_text = "; ".join(
        " ".join(filter(None, [creator.get("given"), creator.get("family")]))
        for creator in creators
        if isinstance(creator, dict)
    )
    content = "\n\n".join(
        filter(
            None,
            [
                source.title,
                creator_text,
                source.abstract,
                source.doi,
                source.url,
            ],
        )
    )
    document = LiteratureDocument(
        path=path,
        filename=f"zotero-{source.id}.txt",
        suffix=".txt",
        size_bytes=len(content.encode("utf-8")),
        source_id=source.id,
        content=content,
    )
    session.add(document)
    session.flush()
    return document


@router.get("/config")
def read_config(session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    browser_settings = session.scalars(select(AppSetting).order_by(AppSetting.key)).all()

    return {
        "app_name": settings.app_name,
        "odk_home": str(settings.odk_home),
        "odk_home_exists": settings.odk_home.exists(),
        "ontology_repo": str(settings.ontology_repo) if settings.ontology_repo else None,
        "require_human_approval": settings.require_human_approval,
        "browser_settings": {
            setting.key: display_value(setting.key, setting.value)
            for setting in browser_settings
        },
    }


@router.post("/config")
def save_config(payload: BrowserSetting, session: Session = Depends(get_session)) -> dict[str, str]:
    set_runtime_values(session, {payload.key: payload.value})
    return {"status": "saved", "key": payload.key}


@router.get("/config/status")
def read_config_status(session: Session = Depends(get_session)) -> dict[str, object]:
    return config_status(session)


@router.post("/config/zotero")
def save_zotero_config(
    payload: ZoteroConfigPayload,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    set_runtime_values(
        session,
        {
            "zotero_library_type": payload.library_type,
            "zotero_library_id": payload.library_id,
            "zotero_api_key": payload.api_key,
            "zotero_collection_key": payload.collection_key,
            "zotero_api_base_url": payload.base_url,
        },
    )
    _upsert_saved_config(
        session,
        kind="zotero",
        values={
            "alias": f"Zotero {payload.library_type} {payload.library_id}",
            "library_type": payload.library_type,
            "library_id": payload.library_id,
            "api_key": payload.api_key,
            "collection_key": payload.collection_key,
            "base_url": payload.base_url,
        },
    )
    return config_status(session)["zotero"]


@router.post("/config/llm")
def save_llm_config(
    payload: LlmConfigPayload,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    set_runtime_values(
        session,
        {
            "llm_provider": payload.provider,
            "llm_api_key": payload.api_key,
            "llm_model": payload.model,
            "llm_base_url": payload.base_url,
        },
    )
    _upsert_saved_config(
        session,
        kind="llm",
        values={
            "alias": f"{payload.provider} {payload.model or ''}".strip(),
            "provider": payload.provider,
            "api_key": payload.api_key,
            "model": payload.model,
            "base_url": payload.base_url,
        },
    )
    return config_status(session)["llm"]


@router.get("/config/saved")
def list_saved_api_configs(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    active_ids = {
        "zotero": _active_config_id(session, "zotero"),
        "llm": _active_config_id(session, "llm"),
    }
    return [
        _public_saved_config(config, active_ids.get(config.get("kind", "")))
        for config in _saved_configs(session)
    ]


@router.post("/config/saved")
def create_saved_api_config(
    payload: SavedApiConfigPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    config = _upsert_saved_config(session, kind=payload.kind, values=payload.model_dump())
    return _public_saved_config(config, config["id"])


@router.post("/config/saved/{config_id}/activate")
def activate_saved_api_config(
    config_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    config = next((item for item in _saved_configs(session) if item.get("id") == config_id), None)
    if config is None:
        raise HTTPException(status_code=404, detail="Saved configuration not found")
    kind = config.get("kind")
    if kind == "zotero":
        set_runtime_values(
            session,
            {
                "zotero_library_type": config.get("library_type"),
                "zotero_library_id": config.get("library_id"),
                "zotero_api_key": config.get("api_key"),
                "zotero_collection_key": config.get("collection_key"),
                "zotero_api_base_url": config.get("base_url"),
                "active_zotero_config_id": config_id,
            },
        )
    elif kind == "llm":
        set_runtime_values(
            session,
            {
                "llm_provider": config.get("provider"),
                "llm_api_key": config.get("api_key"),
                "llm_model": config.get("model"),
                "llm_base_url": config.get("base_url"),
                "active_llm_config_id": config_id,
            },
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported configuration kind")
    return _public_saved_config(config, config_id)


@router.delete("/config/saved/{config_id}")
def delete_saved_api_config(config_id: str, session: Session = Depends(get_session)) -> dict[str, str]:
    configs = _saved_configs(session)
    filtered = [item for item in configs if item.get("id") != config_id]
    if len(filtered) == len(configs):
        raise HTTPException(status_code=404, detail="Saved configuration not found")
    _write_saved_configs(session, filtered)
    return {"status": "deleted", "id": config_id}


@router.post("/config/ontology-path")
def save_ontology_path(
    payload: OntologyPathPayload,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    set_runtime_values(session, {"local_ontology_path": payload.path})
    return config_status(session)["ontology"]


@router.post("/config/test-zotero")
def test_zotero_config(session: Session = Depends(get_session)) -> dict[str, object]:
    config = zotero_config(session)
    try:
        client = ZoteroApiClient(
            ZoteroApiConfig(
                library_type=config.library_type,
                library_id=config.library_id,
                api_key=config.api_key,
                collection_key=config.collection_key,
                base_url=config.base_url,
            )
        )
        items = client.fetch_items(limit=1)
    except ZoteroApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "items_seen": len(items)}


@router.post("/zotero/test")
def test_zotero_connection(session: Session = Depends(get_session)) -> dict[str, object]:
    return test_zotero_config(session)


@router.get("/literature")
def list_literature(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    documents = session.scalars(select(LiteratureDocument).order_by(LiteratureDocument.id)).all()
    return [
        {
            "id": document.id,
            "filename": document.filename,
            "path": document.path,
            "suffix": document.suffix,
            "size_bytes": document.size_bytes,
            "content_length": len(document.content or ""),
            "created_at": document.created_at.isoformat(),
        }
        for document in documents
    ]


@router.post("/literature")
def create_literature(payload: LiteratureCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    if payload.path:
        path = Path(payload.path).expanduser()
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=400, detail="Literature path must be an existing file")
        document = LiteratureDocument.from_path(path)
    elif payload.content:
        filename = payload.filename or "browser-note.txt"
        document = LiteratureDocument(
            path=f"__browser_text__/{filename}",
            filename=filename,
            suffix=Path(filename).suffix or ".txt",
            size_bytes=len(payload.content.encode("utf-8")),
            content=payload.content,
        )
    else:
        raise HTTPException(status_code=400, detail="Provide either path or content")

    session.add(document)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Literature document already exists") from exc
    return {"id": document.id, "filename": document.filename}


def _zotero_select_uri(source: LiteratureSource, session: Session) -> str | None:
    if not source.provider_item_key:
        return None
    config = zotero_config(session)
    if config.library_type == "group" and config.library_id:
        return f"zotero://select/groups/{config.library_id}/items/{source.provider_item_key}"
    return f"zotero://select/library/items/{source.provider_item_key}"


def _source_payload(source: LiteratureSource, session: Session) -> dict[str, Any]:
    return {
        "id": source.id,
        "provider": source.provider,
        "provider_item_key": source.provider_item_key,
        "citation_key": source.citation_key,
        "title": source.title,
        "creators": _json_loads(source.creators_json, []),
        "year": source.year,
        "doi": source.doi,
        "url": source.url,
        "abstract": source.abstract,
        "tags": _json_loads(source.tags_json, []),
        "collections": _json_loads(source.collections_json, []),
        "item_type": source.item_type,
        "publication_venue": source.item_type,
        "zotero_select_uri": _zotero_select_uri(source, session),
        "synced_at": source.synced_at.isoformat() if source.synced_at else None,
    }


@router.get("/zotero/entries")
def list_zotero_entries(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    sources = session.scalars(
        select(LiteratureSource)
        .where(LiteratureSource.provider == "zotero")
        .order_by(LiteratureSource.id)
    ).all()
    return [_source_payload(source, session) for source in sources]


@router.get("/zotero/entries/{source_id}")
def read_zotero_entry(source_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    source = session.get(LiteratureSource, source_id)
    if source is None or source.provider != "zotero":
        raise HTTPException(status_code=404, detail="Zotero entry not found")
    return _source_payload(source, session)


@router.post("/zotero/sync")
def sync_zotero(
    payload: ZoteroSyncPayload,
    session: Session = Depends(get_session),
) -> dict[str, int]:
    config = zotero_config(session)
    try:
        client = ZoteroApiClient(
            ZoteroApiConfig(
                library_type=config.library_type,
                library_id=config.library_id,
                api_key=config.api_key,
                collection_key=payload.collection_key or config.collection_key,
                base_url=config.base_url,
            )
        )
        items = client.fetch_items(
            collection_key=payload.collection_key or config.collection_key,
            limit=payload.limit,
        )
    except ZoteroApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sources = []
    skipped = 0
    for item in items:
        source = parse_source_item(item)
        if source is None:
            skipped += 1
            continue
        sources.append(source)

    try:
        result = import_parsed_sources(session, sources, skipped=skipped, synced=True)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"Zotero sync import failed: {exc}") from exc
    return {
        "fetched": len(items),
        "inserted": result.inserted,
        "updated": result.updated,
        "skipped": result.skipped,
    }


@router.post("/zotero/import-test")
def import_test_zotero_entries(session: Session = Depends(get_session)) -> dict[str, int]:
    sources = [
        ParsedSource(
            provider_item_key="TESTPREFHYD",
            citation_key="timasheff2002test",
            title="Protein-solvent preferential interactions and protein hydration",
            item_type="journalArticle",
            creators=[{"family": "Timasheff", "given": "S. N.", "type": "author"}],
            year="2002",
            doi="10.1146/annurev.biophys.31.082901.134044",
            abstract=(
                "Preferential hydration and preferential exclusion describe protein-solvent "
                "interactions that modulate biochemical reactions and protein stability."
            ),
            tags=["protein hydration", "preferential interaction"],
        ),
        ParsedSource(
            provider_item_key="TESTCOSOLVENT",
            citation_key="cosolventTest",
            title="Cosolvent effects in protein folding assays",
            item_type="journalArticle",
            creators=[{"family": "Curator", "given": "Test", "type": "author"}],
            year="2026",
            abstract=(
                "Cosolvent-mediated stabilization can be observed in folding assays where "
                "osmolytes alter solvent accessibility and reaction kinetics."
            ),
            tags=["cosolvent", "protein folding"],
        ),
    ]
    result = import_parsed_sources(session, sources, synced=False)
    return {"inserted": result.inserted, "updated": result.updated, "skipped": result.skipped}


@router.get("/ontology/status")
def ontology_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    folder = _configured_ontology_path(session)
    scan = scan_ontology_folder(folder)
    selected = _selected_ontology_file(session)
    term_count = 0
    error = None
    if selected is not None and selected.exists():
        try:
            term_count = len(index_ontology_file(selected))
        except Exception as exc:
            error = str(exc)
    return {
        "path": str(folder),
        "selected_file": str(selected) if selected else None,
        "scan": scan,
        "term_count": term_count,
        "indexed": term_count > 0,
        "error": error,
    }


@router.post("/ontology/scan")
def scan_ontology(session: Session = Depends(get_session)) -> dict[str, Any]:
    return scan_ontology_folder(_configured_ontology_path(session))


@router.post("/ontology/select-file")
def select_ontology_file(
    payload: OntologyFilePayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    path = Path(payload.path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail="Selected ontology file does not exist")
    if path.suffix.lower() not in {".owl", ".rdf", ".ttl", ".obo", ".tsv"}:
        raise HTTPException(status_code=400, detail="Unsupported ontology file type")
    set_runtime_values(session, {"local_ontology_file": str(path.resolve())})
    return ontology_status(session)


@router.post("/ontology/index")
def index_ontology(session: Session = Depends(get_session)) -> dict[str, Any]:
    selected = _selected_ontology_file(session)
    if selected is None:
        scan = scan_ontology_folder(_configured_ontology_path(session))
        files = scan.get("files", [])
        selected = _preferred_ontology_file(files)
        if selected is None:
            raise HTTPException(status_code=404, detail="No ontology file found to index")
        set_runtime_values(session, {"local_ontology_file": str(selected)})
    try:
        terms = index_ontology_file(selected)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not index ontology: {exc}") from exc
    return {"selected_file": str(selected), "term_count": len(terms)}


@router.get("/ontology/terms")
def ontology_terms(
    q: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    terms = _indexed_terms(session)
    selected = search_terms(terms, q, limit=limit) if q else terms[:limit]
    return [term.to_dict() for term in selected]


@router.get("/ontology/search")
def ontology_search(
    q: str,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return [term.to_dict() for term in search_terms(_indexed_terms(session), q, limit=limit)]


@router.get("/ontology/terms/{term_id}")
def ontology_term(term_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    for term in _indexed_terms(session):
        if term.term_id == term_id or term.iri == term_id:
            return term.to_dict()
    raise HTTPException(status_code=404, detail="Ontology term not found")


@router.get("/ontology/graph")
def ontology_graph(limit: int = 80, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return _graph_from_terms(_indexed_terms(session), limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not build ontology graph: {exc}") from exc


@router.get("/meta-ontology/graph")
def meta_ontology_graph() -> dict[str, Any]:
    nodes = [
        {"id": "source", "label": "Source", "type": "concept", "definition": "Zotero entry or literature document."},
        {"id": "evidence", "label": "Evidence", "type": "concept", "definition": "Quoted or inferred source support."},
        {"id": "candidate", "label": "Candidate", "type": "concept", "definition": "Proposed ontology term under review."},
        {"id": "local_match", "label": "Local PPO Match", "type": "concept", "definition": "Existing term from the indexed local ontology."},
        {"id": "ols_match", "label": "OLS Match", "type": "concept", "definition": "External EMBL-EBI OLS term candidate."},
        {"id": "decision", "label": "Curator Decision", "type": "concept", "definition": "Human review decision for the candidate."},
        {"id": "export", "label": "Export", "type": "concept", "definition": "Approved ROBOT/ODK/Protégé handoff."},
    ]
    edges = [
        {"id": "source-evidence", "source": "source", "target": "evidence", "label": "provides"},
        {"id": "evidence-candidate", "source": "evidence", "target": "candidate", "label": "supports"},
        {"id": "candidate-local", "source": "candidate", "target": "local_match", "label": "compared with"},
        {"id": "candidate-ols", "source": "candidate", "target": "ols_match", "label": "looked up in"},
        {"id": "local-decision", "source": "local_match", "target": "decision", "label": "informs"},
        {"id": "ols-decision", "source": "ols_match", "target": "decision", "label": "informs"},
        {"id": "decision-export", "source": "decision", "target": "export", "label": "controls"},
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/candidates")
def list_candidates(
    include_rejected: bool = False,
    rejected_only: bool = False,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    statement = select(CandidateTermRecord).order_by(CandidateTermRecord.id)
    if rejected_only:
        statement = statement.where(CandidateTermRecord.review_status == ReviewStatus.PERMANENTLY_REJECTED.value)
    elif not include_rejected:
        statement = statement.where(
            CandidateTermRecord.review_status.in_([
                ReviewStatus.NEW.value,
                ReviewStatus.IN_REVIEW.value,
                ReviewStatus.NEEDS_MORE_EVIDENCE.value,
                ReviewStatus.DEFERRED.value,
            ])
        )
    candidates = session.scalars(statement).all()
    return [_candidate_payload(candidate) for candidate in candidates]


@router.post("/extraction/candidates")
def extract_candidates(
    payload: ExtractionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if payload.document_id is not None:
        document = session.get(LiteratureDocument, payload.document_id)
    elif payload.source_id is not None:
        source = session.get(LiteratureSource, payload.source_id)
        if source is None or source.provider != "zotero":
            raise HTTPException(status_code=404, detail="Zotero entry not found")
        document = _document_from_source(session, source)
    else:
        raise HTTPException(status_code=400, detail="Select a Zotero entry or literature document")

    if document is None:
        raise HTTPException(status_code=404, detail="Literature document not found")

    text = document.content or payload.guidance or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="Selected source has no extractable text")

    try:
        result = extract_candidates_with_optional_llm(
            text,
            document_id=document.id,
            filename=document.filename,
            config=llm_config(session),
            guidance=payload.guidance,
            use_llm=payload.use_llm,
        )
    except (LlmUnavailableError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    inserted, skipped = persist_candidates(
        session,
        document_id=document.id,
        response=result.response,
        provider=result.provider,
        model=result.model,
        raw_response=result.raw_response,
    )
    candidates = session.scalars(
        select(CandidateTermRecord)
        .where(CandidateTermRecord.document_id == document.id)
        .order_by(CandidateTermRecord.id)
    ).all()
    return {
        "document_id": document.id,
        "inserted": inserted,
        "skipped": skipped,
        "used_llm": result.used_llm,
        "message": result.message,
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
    }


@router.post("/candidates/ols")
def refresh_all_draft_ols_matches(session: Session = Depends(get_session)) -> dict[str, int]:
    candidates = session.scalars(
        select(CandidateTermRecord)
        .where(CandidateTermRecord.review_status.in_([
            ReviewStatus.NEW.value,
            ReviewStatus.IN_REVIEW.value,
            ReviewStatus.NEEDS_MORE_EVIDENCE.value,
        ]))
        .order_by(CandidateTermRecord.id)
    ).all()
    service = OlsLookupService()
    updated = 0
    failed = 0
    for candidate in candidates:
        try:
            matches = [match.to_dict() for match in service.search(candidate.label)]
        except Exception:
            failed += 1
            continue
        candidate.ols_matches_json = json.dumps(matches)
        candidate.ols_lookup_status = "performed"
        updated += 1
    session.commit()
    return {"updated": updated, "failed": failed}


@router.post("/candidates")
def create_candidate(payload: CandidateCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    document = (
        session.get(LiteratureDocument, payload.document_id)
        if payload.document_id is not None
        else _get_or_create_manual_document(session)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Literature document not found")

    candidate = CandidateTermRecord(
        candidate_id=build_candidate_id(document.id, payload.label),
        document_id=document.id,
        label=payload.label.strip(),
        normalized_label=normalize_label(payload.label),
        proposed_definition=payload.proposed_definition,
        synonyms_json=json.dumps(payload.synonyms),
        proposed_parent=payload.proposed_parent,
        confidence_score=payload.confidence_score,
        review_status=ReviewStatus.NEW.value,
        evidence_json=json.dumps(payload.evidence),
        curator_rationale=payload.curator_rationale,
        source_evidence=payload.source_evidence,
        mappings_json=json.dumps(payload.mappings),
    )
    session.add(candidate)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Candidate already exists for this document") from exc
    return _candidate_payload(candidate)


@router.patch("/candidates/{candidate_id}")
def update_candidate(
    candidate_id: int,
    payload: CandidateUpdate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    updates = payload.model_dump(exclude_unset=True)
    if "label" in updates and updates["label"] is not None:
        candidate.label = updates["label"].strip()
        candidate.normalized_label = normalize_label(candidate.label)
    if "proposed_definition" in updates:
        candidate.proposed_definition = updates["proposed_definition"]
    if "synonyms" in updates and updates["synonyms"] is not None:
        candidate.synonyms_json = json.dumps(updates["synonyms"])
    if "proposed_parent" in updates:
        candidate.proposed_parent = updates["proposed_parent"]
    if "confidence_score" in updates and updates["confidence_score"] is not None:
        candidate.confidence_score = updates["confidence_score"]
    if "evidence" in updates and updates["evidence"] is not None:
        candidate.evidence_json = json.dumps(updates["evidence"])
    if "review_status" in updates and updates["review_status"] is not None:
        candidate.review_status = updates["review_status"].value
    if "curator_rationale" in updates:
        candidate.curator_rationale = updates["curator_rationale"]
    if "source_evidence" in updates:
        candidate.source_evidence = updates["source_evidence"]
    if "mappings" in updates and updates["mappings"] is not None:
        candidate.mappings_json = json.dumps(updates["mappings"])
    if "selected_ols" in updates:
        candidate.selected_ols_json = json.dumps(updates["selected_ols"]) if updates["selected_ols"] else None
    if "selected_local" in updates:
        candidate.selected_local_json = (
            json.dumps(updates["selected_local"]) if updates["selected_local"] else None
        )
    if "curator_decision" in updates and updates["curator_decision"] is not None:
        candidate.curator_decision = updates["curator_decision"]

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Candidate label conflicts in this document") from exc
    return _candidate_payload(candidate)


@router.post("/candidates/{candidate_id}/review")
def review_candidate(
    candidate_id: int,
    payload: ReviewAction,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    candidate.review_status = payload.status
    if payload.rationale is not None:
        candidate.curator_rationale = payload.rationale
    session.commit()
    return _candidate_payload(candidate)


@router.post("/candidates/{candidate_id}/ols")
def refresh_ols_matches(candidate_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    try:
        matches = [match.to_dict() for match in OlsLookupService().search(candidate.label)]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OLS lookup failed: {exc}") from exc

    candidate.ols_matches_json = json.dumps(matches)
    candidate.ols_lookup_status = "performed"
    session.commit()
    return _candidate_payload(candidate)


@router.post("/candidates/{candidate_id}/ols-selection")
def select_ols_match(
    candidate_id: int,
    payload: OlsSelection,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    candidate.selected_ols_json = json.dumps(payload.match) if payload.match else None
    if payload.match:
        candidate.curator_decision = "use_existing_ols_term"
    elif candidate.curator_decision == "use_existing_ols_term":
        candidate.curator_decision = "needs_review"
    session.commit()
    return _candidate_payload(candidate)


@router.post("/candidates/{candidate_id}/match-ols")
def match_ols_candidate(candidate_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return refresh_ols_matches(candidate_id, session)


@router.post("/candidates/{candidate_id}/select-ols-match")
def select_ols_candidate_match(
    candidate_id: int,
    payload: OlsSelection,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return select_ols_match(candidate_id, payload, session)


@router.post("/candidates/{candidate_id}/match-local-ontology")
def match_local_ontology_candidate(
    candidate_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    try:
        terms = _indexed_terms(session)
        matches = match_local_terms(
            candidate.label,
            _json_loads(candidate.synonyms_json, []),
            terms,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Local ontology lookup failed: {exc}") from exc
    candidate.local_matches_json = json.dumps(matches)
    candidate.local_lookup_status = "performed"
    session.commit()
    return _candidate_payload(candidate)


@router.post("/candidates/{candidate_id}/select-local-match")
def select_local_match(
    candidate_id: int,
    payload: LocalSelection,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    candidate.selected_local_json = json.dumps(payload.match) if payload.match else None
    if payload.match:
        candidate.curator_decision = "use_existing_local_term"
    elif candidate.curator_decision == "use_existing_local_term":
        candidate.curator_decision = "needs_review"
    session.commit()
    return _candidate_payload(candidate)


@router.post("/candidates/{candidate_id}/decision")
def set_candidate_decision(
    candidate_id: int,
    payload: CandidateDecisionPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    candidate.curator_decision = payload.decision
    if payload.decision == "rejected":
        candidate.review_status = ReviewStatus.REJECTED.value
    session.commit()
    return _candidate_payload(candidate)


@router.get("/candidates/rejected")
def list_permanently_rejected_candidates(
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return list_candidates(rejected_only=True, session=session)


@router.post("/candidates/{candidate_id}/permanent-reject")
def permanently_reject_candidate(
    candidate_id: int,
    payload: RejectionPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    candidate.review_status = ReviewStatus.PERMANENTLY_REJECTED.value
    candidate.curator_decision = "rejected"
    candidate.rejection_reason = payload.reason
    candidate.permanently_rejected_at = datetime.now(timezone.utc)
    session.commit()
    return _candidate_payload(candidate)


@router.post("/candidates/{candidate_id}/restore")
def restore_candidate(
    candidate_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    candidate = _get_candidate(session, candidate_id)
    candidate.review_status = ReviewStatus.IN_REVIEW.value
    candidate.curator_decision = "needs_review"
    candidate.rejection_reason = None
    candidate.permanently_rejected_at = None
    session.commit()
    return _candidate_payload(candidate)


@router.post("/refine")
def refine_candidates(
    payload: RefinementRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    document = (
        session.get(LiteratureDocument, payload.document_id)
        if payload.document_id is not None
        else _get_or_create_manual_document(session)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Literature document not found")

    label = payload.guidance.splitlines()[0].strip(" -*:\t")[:120]
    if not label:
        raise HTTPException(status_code=400, detail="Guidance must include candidate text")

    candidate = CandidateTermRecord(
        candidate_id=build_candidate_id(document.id, label),
        document_id=document.id,
        label=label,
        normalized_label=normalize_label(label),
        proposed_definition=f"Candidate proposed from curator guidance: {payload.guidance}",
        synonyms_json="[]",
        proposed_parent=None,
        confidence_score=0.35,
        review_status=ReviewStatus.IN_REVIEW.value,
        evidence_json=json.dumps(
            [
                {
                    "quoted_text": payload.guidance,
                    "section_title": "curator guidance",
                    "page_number": None,
                    "char_start": None,
                    "char_end": None,
                    "direct_or_inferred": "contextual",
                }
            ]
        ),
        curator_rationale="Generated from browser refinement guidance.",
        source_evidence=payload.guidance,
        refinement_guidance=payload.guidance,
    )
    session.add(candidate)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(CandidateTermRecord).where(
                CandidateTermRecord.document_id == document.id,
                CandidateTermRecord.normalized_label == normalize_label(label),
            )
        )
        if existing is None:
            raise
        existing.refinement_guidance = payload.guidance
        existing.review_status = ReviewStatus.IN_REVIEW.value
        session.commit()
        candidate = existing

    prompt_preview = None
    if document.content:
        prompt_preview = build_candidate_extraction_prompt(
            f"Curator guidance:\n{payload.guidance}\n\n{document.content}",
            document_id=document.id,
            filename=document.filename,
            chars=4000,
        )
    return {"candidate": _candidate_payload(candidate), "prompt_preview": prompt_preview}


@router.get("/exports/approved.{export_format}")
def export_approved(
    export_format: Literal["robot.tsv", "candidates.tsv"],
    session: Session = Depends(get_session),
) -> StreamingResponse:
    candidates = session.scalars(
        select(CandidateTermRecord)
        .where(CandidateTermRecord.review_status.in_([
            ReviewStatus.APPROVED.value,
            ReviewStatus.APPROVED_WITH_EDITS.value,
        ]))
        .order_by(CandidateTermRecord.id)
    ).all()

    output = io.StringIO()
    if export_format == "robot.tsv":
        write_robot_template(list(candidates), output)
        filename = "approved_candidates.robot.tsv"
    else:
        write_candidate_tsv(list(candidates), output)
        filename = "approved_candidates.tsv"

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
