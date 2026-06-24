from __future__ import annotations

import io
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.logging import write_audit_event
from backend.app.config import get_settings
from backend.app.db.session import get_session
from backend.app.extraction.prompts import build_candidate_extraction_prompt
from backend.app.extraction.service import build_candidate_id, normalize_label, persist_candidates
from backend.app.llm.curation import (
    CURATION_PROMPT_SETTING_KEY,
    DEFAULT_CURATION_PROMPT,
    CurationInputError,
    CurationResponseError,
    run_curation_suggestion_workflow,
)
from backend.app.llm.clients import LlmClientError, generate_text, provider_catalog, test_llm_connection
from backend.app.llm.presets import normalize_provider_id
from backend.app.llm.service import LlmUnavailableError, extract_candidates_with_optional_llm
from backend.app.literature.exporter import (
    refresh_literature_markdown_repository,
    is_valid_zotero_item_key,
    zotero_select_uri,
)
from backend.app.literature.pipeline import run_literature_pipeline
from backend.app.literature.canonical import (
    DEFAULT_EXTRACTION_MODE,
    LiteratureExtractionError,
    RepositoryPaths,
    build_combined as build_canonical_combined,
    deduplicate as deduplicate_canonical,
    import_directory as import_canonical_directory,
    import_identified_item,
    test_publisher_api as run_publisher_api_test,
    cleanup_unpromoted_staged,
    list_entries as list_canonical_entries,
    list_curated_entries,
    migrate_old as migrate_old_literature,
    promote_staged_entry,
    reject_staged_entry,
    reset_repository as reset_canonical_repository,
    update_curated_entry,
    update_staged_entry,
    write_project_settings,
)
from backend.app.literature.publisher_xml import ElsevierApiConfig, LiteratureIdentification
from backend.app.literature.repository import (
    LiteratureRepositoryLoadResult,
    build_combined_context_files,
    load_llm_ready_repository_with_diagnostics,
    literature_repository_report,
    literature_context_for_entry_generation,
    regenerate_clean_markdown,
    regenerate_llm_context,
    repository_status,
    reset_literature_repository,
    retry_literature_extraction,
    update_literature_review_metadata,
)
from backend.app.literature.quality import extractor_availability, should_include_for_automatic_llm
from backend.app.models.core import ReviewStatus
from backend.app.models.db import (
    AppSetting,
    CandidateTermRecord,
    CurationRun,
    OdkOperationLog,
    Project,
    Suggestion,
    ExtractionRun,
    LiteratureDocument,
    LiteratureSource,
)
from backend.app.odk.integration import write_candidate_tsv, write_robot_template
from backend.app.odk.workflow import config_from_settings, run_approved_candidate_workflow
from backend.app.ontology.local import (
    index_ontology_file,
    match_local_terms,
    ontology_tree_payload,
    scan_ontology_folder,
    search_terms,
)
from backend.app.ontology.relations import relation_type_payload
from backend.app.ontology.ols import OlsLookupService
from backend.app.projects import (
    PROJECT_TYPES,
    PROMPT_STRATEGIES,
    add_review,
    compare_runs,
    compute_evaluation,
    create_curation_run,
    create_project,
    export_suggestions_tsv,
    get_project,
    latest_reviews_by_suggestion,
    log_odk_operation,
    persist_suggestions,
    project_payload,
    review_payload,
    select_project,
    suggest_base_iri,
    suggestion_payload,
    update_project_metadata,
    validate_project_odk,
)
from backend.app.services.runtime_config import (
    config_status,
    display_value,
    literature_pipeline_config,
    literature_config,
    llm_config,
    publisher_config,
    set_runtime_values,
    zotero_config,
)
from backend.app.zotero.client import ZoteroApiClient, ZoteroApiConfig, ZoteroApiError
from backend.app.zotero.importer import ParsedSource, import_parsed_sources, parse_source_item


router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


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
    api_key_env_var: str | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    retry_count: int | None = None
    stream: bool | None = None


class SavedApiConfigPayload(BaseModel):
    kind: Literal["zotero", "llm", "publisher"]
    alias: str | None = None
    provider: str | None = None
    library_type: Literal["user", "group"] | None = None
    library_id: str | None = None
    api_key: str | None = None
    api_key_env_var: str | None = None
    collection_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    retry_count: int | None = None
    stream: bool | None = None
    inst_token: str | None = None
    enabled: bool | None = None
    extraction_mode: Literal["publisher_api_required", "pdf_fallback_allowed", "pdf_only"] | None = None


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


class LiteratureResetPayload(BaseModel):
    confirm: bool = False


class LiteraturePipelineConfigPayload(BaseModel):
    zotero_literature_storage_path: str | None = None


class CanonicalLiteratureImportPayload(BaseModel):
    project: str | int | None = None
    zotero_storage: str | None = None
    pdf_dir: str | None = None
    keep_sources: bool = True
    overwrite: bool = False
    local_pdf_path: str | None = None
    zotero_key: str | None = None
    doi: str | None = None
    pii: str | None = None
    sciencedirect_url: str | None = None
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: str | None = None
    journal: str | None = None
    extraction_mode: Literal["publisher_api_required", "pdf_fallback_allowed", "pdf_only"] | None = None
    allow_pdf_fallback: bool = False


class CanonicalLiteratureActionPayload(BaseModel):
    project: str | int | None = None
    apply: bool = False
    confirm: bool = False
    dry_run: bool = False


class LiteratureEntryEditPayload(BaseModel):
    project: str | int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    markdown: str | None = None
    project_tags: list[str] | None = None


class StagedLiteratureDecisionPayload(BaseModel):
    project: str | int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    markdown: str | None = None
    project_tags: list[str] | None = None
    delete: bool = False
    confirm: bool = False


class PublisherConfigPayload(BaseModel):
    elsevier_api_key: str | None = None
    elsevier_inst_token: str | None = None
    elsevier_api_base_url: str | None = None
    publisher_api_enrichment_enabled: bool | None = None
    literature_extraction_mode: Literal["publisher_api_required", "pdf_fallback_allowed", "pdf_only"] | None = None


class PublisherApiTestPayload(BaseModel):
    project: str | int | None = None
    doi: str | None = None
    pii: str | None = None
    sciencedirect_url: str | None = None
    write_artifacts: bool = True


class CurationPromptPayload(BaseModel):
    prompt: str = Field(min_length=1)


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
    graph_review: dict[str, Any] | None = None


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
    dry_run: bool = False


class LiteratureReviewUpdatePayload(BaseModel):
    markdown_file: str = Field(min_length=1)
    include_in_llm_extraction: bool | None = None
    metadata_match_status: Literal["matched", "weak_match", "metadata_mismatch", "unknown"] | None = None
    document_role: Literal[
        "domain_article",
        "methodology_article",
        "review_article",
        "supplementary_information",
        "unknown",
    ] | None = None
    requires_manual_review: bool | None = None
    state: Literal[
        "imported",
        "extracted",
        "extraction_failed",
        "validation_failed",
        "needs_review",
        "cleaned",
        "context_ready",
        "ready_for_llm",
        "blocked",
    ] | None = None


class LiteratureActionPayload(BaseModel):
    markdown_file: str = Field(min_length=1)
    engine: str | None = None


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


class OdkWorkflowPayload(BaseModel):
    dry_run: bool = True
    production: bool = False
    suggestion_file: str | None = None


class ProjectCreatePayload(BaseModel):
    name: str = Field(min_length=1)
    ontology_id: str = Field(min_length=1)
    ontology_title: str | None = None
    project_type: Literal[
        "upper_bioprocess_ontology",
        "domain_ontology",
        "module",
        "application_ontology",
        "existing_ontology_project",
        "imported_reference_ontology",
    ] = "domain_ontology"
    parent_project_id: str | int | None = None
    ontology_scope: list[str] = Field(default_factory=list)
    minimal_scope_notes: str | None = None
    ontology_namespace: str | None = None
    base_iri: str | None = None
    local_workspace_path: str | None = None
    github_url: str | None = None
    local_git_repository_path: str | None = None
    zotero_literature_source_path: str | None = None
    selected_ontology_imports: list[str] = Field(default_factory=list)
    odk_repo_path: str | None = None
    editable_ontology_path: str | None = None
    built_ontology_path: str | None = None
    literature_repository_path: str | None = None
    term_id_pattern: str | None = None
    description: str | None = None
    activate: bool = True


class ProjectUpdatePayload(BaseModel):
    name: str | None = None
    description: str | None = None
    ontology_id: str | None = None
    ontology_title: str | None = None
    project_type: Literal[
        "upper_bioprocess_ontology",
        "domain_ontology",
        "module",
        "application_ontology",
        "existing_ontology_project",
        "imported_reference_ontology",
    ] | None = None
    parent_project_id: str | int | None = None
    ontology_scope: list[str] | None = None
    minimal_scope_notes: str | None = None
    ontology_namespace: str | None = None
    base_iri: str | None = None
    local_workspace_path: str | None = None
    github_url: str | None = None
    local_git_repository_path: str | None = None
    odk_repo_path: str | None = None
    editable_ontology_path: str | None = None
    built_ontology_path: str | None = None
    literature_repository_path: str | None = None


class CurationRunCreatePayload(BaseModel):
    project_id: str | int | None = None
    name: str | None = None
    strategy: Literal[
        "literature_only",
        "ontology_only",
        "literature_plus_ontology",
        "structured_relation_extraction",
    ]
    model: str | None = None
    prompt_text: str | None = None
    context_configuration: dict[str, Any] = Field(default_factory=dict)
    raw_output: str | None = None


class SuggestionImportPayload(BaseModel):
    raw_output: str = Field(min_length=1)


class ReviewDecisionPayload(BaseModel):
    status: Literal["accepted", "edited", "rejected", "duplicate", "unsupported", "further_review"]
    reviewer: str | None = None
    edited_label: str | None = None
    edited_definition: str | None = None
    edited_parent_class: str | None = None
    edited_relation: str | None = None
    edited_target: str | None = None
    relation_correct: bool | None = None
    comment: str | None = None
    review_time_seconds: int | None = Field(default=None, ge=0)


class EvaluationComparePayload(BaseModel):
    first_run_id: int
    second_run_id: int


class OdkOperationPayload(BaseModel):
    operation: str = Field(min_length=1)
    command: str | None = None
    working_directory: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    status: str = "logged"


class ProjectMetadataSuggestionPayload(BaseModel):
    idea: str = Field(min_length=3, max_length=500)


class LiteratureProjectTagsPayload(BaseModel):
    project_tags: list[str] = Field(default_factory=list)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _clean_string_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _project_or_404(session: Session, project_ref: str | int | None = None) -> Project:
    try:
        return get_project(session, project_ref)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects")
def list_projects(session: Session = Depends(get_session)) -> dict[str, Any]:
    projects = session.scalars(select(Project).order_by(Project.active.desc(), Project.name)).all()
    active = next((project for project in projects if project.active), None)
    return {
        "project_types": sorted(PROJECT_TYPES),
        "active_project": project_payload(active, session) if active else None,
        "projects": [project_payload(project, session) for project in projects],
    }


@router.post("/projects")
def create_project_endpoint(
    payload: ProjectCreatePayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        project = create_project(
            session,
            name=payload.name,
            ontology_id=payload.ontology_id,
            ontology_title=payload.ontology_title,
            project_type=payload.project_type,
            parent_project_ref=payload.parent_project_id,
            ontology_scope=payload.ontology_scope,
            minimal_scope_notes=payload.minimal_scope_notes,
            ontology_namespace=payload.ontology_namespace,
            base_iri=payload.base_iri,
            local_workspace_path=Path(payload.local_workspace_path or "."),
            github_url=payload.github_url,
            local_git_repository_path=payload.local_git_repository_path,
            zotero_literature_source_path=payload.zotero_literature_source_path,
            odk_repo_path=payload.odk_repo_path,
            editable_ontology_path=payload.editable_ontology_path,
            built_ontology_path=payload.built_ontology_path,
            literature_repository_path=payload.literature_repository_path,
            term_id_pattern=payload.term_id_pattern,
            description=payload.description,
            activate=payload.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already exists" in str(exc) else 400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return project_payload(project, session)


@router.get("/projects/suggest-base-iri")
def suggest_project_base_iri(ontology_id: str) -> dict[str, Any]:
    return {"ontology_id": ontology_id, "base_iri": suggest_base_iri(ontology_id)}


def _parse_project_metadata_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    candidates = [cleaned]
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
    if fenced and fenced not in candidates:
        candidates.append(fenced)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("LLM returned JSON, but it was not a metadata object.")
    raise ValueError("LLM returned text that was not valid JSON project metadata.")


@router.post("/projects/suggest-metadata")
def suggest_project_metadata(
    payload: ProjectMetadataSuggestionPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    config = llm_config(session)
    if not config.provider or not config.resolved_api_key:
        raise HTTPException(
            status_code=400,
            detail="LLM is not configured. Enter LLM settings or create the project manually.",
        )
    prompt = (
        "Suggest concise metadata for an ontology-development project. "
        "Return only JSON with keys: project_name, ontology_id, project_type, short_description, "
        "base_iri, minimal_scope_notes. "
        "Allowed project_type values are upper_bioprocess_ontology, domain_ontology, module, "
        "application_ontology, existing_ontology_project. "
        "Use a short ontology_id and a base IRI like http://purl.obolibrary.org/obo/<id>.owl.\n\n"
        f"Project idea: {payload.idea}"
    )
    try:
        result = generate_text(
            prompt,
            system_prompt="You help draft short ontology project metadata. Return compact JSON only.",
            config=config,
        )
        suggestion = _parse_project_metadata_json(result.text)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LlmClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ontology_id = str(suggestion.get("ontology_id") or "").strip()
    project_type = str(suggestion.get("project_type") or "domain_ontology").strip()
    if project_type not in PROJECT_TYPES:
        project_type = "domain_ontology"
    if ontology_id and not suggestion.get("base_iri"):
        suggestion["base_iri"] = suggest_base_iri(ontology_id)
    return {
        "ok": True,
        "suggestion": {
            "project_name": str(suggestion.get("project_name") or suggestion.get("name") or "").strip(),
            "ontology_id": ontology_id,
            "project_type": project_type,
            "short_description": str(suggestion.get("short_description") or suggestion.get("description") or "").strip(),
            "base_iri": str(suggestion.get("base_iri") or "").strip(),
            "minimal_scope_notes": str(suggestion.get("minimal_scope_notes") or "").strip(),
        },
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
    }


@router.get("/projects/active")
def read_active_project(session: Session = Depends(get_session)) -> dict[str, Any]:
    return project_payload(_project_or_404(session), session)


@router.post("/projects/{project_ref}/select")
def select_project_endpoint(project_ref: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        project = select_project(session, project_ref)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return project_payload(project, session)


@router.post("/projects/{project_ref}/activate")
def activate_project_endpoint(project_ref: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return select_project_endpoint(project_ref, session)


@router.get("/projects/{project_ref}")
def read_project(project_ref: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return project_payload(_project_or_404(session, project_ref), session)


@router.get("/projects/{project_ref}/children")
def list_project_children(project_ref: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    project = _project_or_404(session, project_ref)
    children = session.scalars(
        select(Project).where(Project.parent_project_id == project.id).order_by(Project.name)
    ).all()
    return [project_payload(child, session) for child in children]


@router.patch("/projects/{project_ref}")
def update_project(
    project_ref: str,
    payload: ProjectUpdatePayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project = _project_or_404(session, project_ref)
    try:
        updates = payload.model_dump(exclude_unset=True)
        if "local_workspace_path" in updates:
            workspace = updates.pop("local_workspace_path")
            if workspace:
                updates["local_path"] = str(Path(workspace))
        project = update_project_metadata(session, project, updates)
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already exists" in str(exc) else 400, detail=str(exc)) from exc
    return project_payload(project, session)


@router.get("/curation/prompt-strategies")
def list_prompt_strategies() -> dict[str, str]:
    return PROMPT_STRATEGIES


@router.post("/curation/runs")
def create_curation_run_endpoint(
    payload: CurationRunCreatePayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project = _project_or_404(session, payload.project_id)
    try:
        run = create_curation_run(
            session,
            project,
            name=payload.name,
            strategy=payload.strategy,
            model=payload.model,
            prompt_text=payload.prompt_text,
            context_configuration=payload.context_configuration,
            raw_output=payload.raw_output,
        )
        parsed = 0
        warning = None
        if payload.raw_output:
            parsed, warning = persist_suggestions(session, run, payload.raw_output)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": run.id,
        "project_id": run.project_id,
        "name": run.name,
        "prompt_strategy": run.prompt_strategy,
        "status": run.status,
        "parsed_suggestions": parsed,
        "warning": warning,
    }


@router.get("/curation/runs")
def list_curation_runs(
    project_id: str | int | None = None,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    project = _project_or_404(session, project_id)
    runs = session.scalars(
        select(CurationRun).where(CurationRun.project_id == project.id).order_by(CurationRun.created_at.desc())
    ).all()
    return [
        {
            "id": run.id,
            "project_id": run.project_id,
            "name": run.name,
            "model": run.model,
            "prompt_strategy": run.prompt_strategy,
            "context_configuration": _json_loads(run.context_configuration_json, {}),
            "literature_snapshot_path": run.literature_snapshot_path,
            "ontology_snapshot_path": run.ontology_snapshot_path,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }
        for run in runs
    ]


@router.post("/curation/runs/{run_id}/suggestions")
def import_run_suggestions(
    run_id: int,
    payload: SuggestionImportPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    run = session.get(CurationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Curation run not found")
    count, warning = persist_suggestions(session, run, payload.raw_output)
    return {"run_id": run.id, "parsed_suggestions": count, "warning": warning, "status": run.status}


@router.get("/suggestions")
def list_suggestions(
    project_id: str | int | None = None,
    run_id: int | None = None,
    status: str | None = None,
    suggestion_type: str | None = None,
    evidence: Literal["any", "with", "without"] = "any",
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    project = _project_or_404(session, project_id)
    statement = select(Suggestion).where(Suggestion.project_id == project.id)
    if run_id is not None:
        statement = statement.where(Suggestion.curation_run_id == run_id)
    if suggestion_type:
        statement = statement.where(Suggestion.suggestion_type == suggestion_type)
    suggestions = session.scalars(statement.order_by(Suggestion.created_at.desc())).all()
    reviews = latest_reviews_by_suggestion(session, [item.id for item in suggestions])
    filtered = []
    for suggestion in suggestions:
        latest = reviews.get(suggestion.id)
        review_status = latest.status if latest else "unreviewed"
        has_evidence = bool(suggestion.evidence_text or _json_loads(suggestion.evidence_json, []))
        if status and review_status != status:
            continue
        if evidence == "with" and not has_evidence:
            continue
        if evidence == "without" and has_evidence:
            continue
        filtered.append(suggestion_payload(suggestion, latest))
    return filtered


@router.post("/suggestions/{suggestion_id}/review")
def review_suggestion(
    suggestion_id: int,
    payload: ReviewDecisionPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    suggestion = session.get(Suggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    try:
        review = add_review(session, suggestion, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return review_payload(review) or {}


@router.post("/evaluation/compute")
def compute_evaluation_endpoint(
    project_id: str | int | None = None,
    run_id: int | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project = _project_or_404(session, project_id)
    return compute_evaluation(session, project, run_id)


@router.post("/evaluation/compare")
def compare_evaluation_endpoint(
    payload: EvaluationComparePayload,
    project_id: str | int | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project = _project_or_404(session, project_id)
    return compare_runs(session, project, payload.first_run_id, payload.second_run_id)


@router.get("/projects/{project_ref}/odk/validate")
def validate_project_odk_endpoint(project_ref: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project = _project_or_404(session, project_ref)
    return validate_project_odk(session, project)


@router.post("/projects/{project_ref}/odk/logs")
def log_project_odk_operation(
    project_ref: str,
    payload: OdkOperationPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project = _project_or_404(session, project_ref)
    log = log_odk_operation(session, project, **payload.model_dump())
    return {
        "id": log.id,
        "project_id": log.project_id,
        "operation": log.operation,
        "status": log.status,
        "exit_code": log.exit_code,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("/projects/{project_ref}/odk/logs")
def list_project_odk_logs(project_ref: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    project = _project_or_404(session, project_ref)
    logs = session.scalars(
        select(OdkOperationLog).where(OdkOperationLog.project_id == project.id).order_by(OdkOperationLog.created_at.desc())
    ).all()
    return [
        {
            "id": log.id,
            "operation": log.operation,
            "command": log.command,
            "working_directory": log.working_directory,
            "stdout": log.stdout,
            "stderr": log.stderr,
            "exit_code": log.exit_code,
            "status": log.status,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.get("/projects/{project_ref}/exports/accepted.robot.tsv")
def export_project_accepted_suggestions(
    project_ref: str,
    include_further_review: bool = False,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    project = _project_or_404(session, project_ref)
    content = export_suggestions_tsv(session, project, include_further_review=include_further_review)
    return StreamingResponse(
        io.StringIO(content),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": "attachment; filename=project_accepted_suggestions.robot.tsv"},
    )


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
        "graph_review": _json_loads(candidate.graph_review_json, {}),
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


def _get_or_create_repository_document(session: Session, content: str) -> LiteratureDocument:
    document = session.scalar(
        select(LiteratureDocument).where(LiteratureDocument.path == "__llm_ready_literature_repository__")
    )
    if document is None:
        document = LiteratureDocument(
            path="__llm_ready_literature_repository__",
            filename="LLM-ready literature Markdown corpus",
            suffix=".md",
            size_bytes=len(content.encode("utf-8")),
            content=content,
        )
        session.add(document)
        session.flush()
        return document

    document.content = content
    document.size_bytes = len(content.encode("utf-8"))
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


def _curation_prompt(session: Session) -> str:
    setting = session.get(AppSetting, CURATION_PROMPT_SETTING_KEY)
    return setting.value if setting is not None and setting.value else DEFAULT_CURATION_PROMPT


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


def _existing_file(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    return path if path.exists() and path.is_file() else None


def resolve_project_ontology_file(project: Project) -> tuple[Path | None, str | None]:
    explicit_built = _existing_file(project.built_ontology_path)
    if explicit_built:
        return explicit_built, "built_ontology_path"
    explicit_editable = _existing_file(project.editable_ontology_path)
    if explicit_editable:
        return explicit_editable, "editable_ontology_path"

    # List of built/released candidates
    built_candidates = [
        Path(project.local_path) / "target" / project.ontology_id / "src" / "ontology" / f"{project.ontology_id}-simple.obo",
        Path(project.odk_repo_path or "") / "target" / project.ontology_id / "src" / "ontology" / f"{project.ontology_id}-simple.obo",
        Path(project.local_path) / "ontology" / "releases" / f"{project.ontology_id}-simple.obo",
        Path(project.local_path) / "ontology" / f"{project.ontology_id}-simple.obo",
        Path(project.odk_repo_path or "") / "src" / "ontology" / f"{project.ontology_id}-simple.obo",
        Path(project.odk_repo_path or "") / f"{project.ontology_id}-simple.obo",
    ]
    for p in built_candidates:
        if p and p.exists() and p.is_file():
            return p, "built_obo"

    # List of edit/editable candidates
    edit_candidates = [
        Path(project.local_path) / "target" / project.ontology_id / "src" / "ontology" / f"{project.ontology_id}-edit.owl",
        Path(project.odk_repo_path or "") / "target" / project.ontology_id / "src" / "ontology" / f"{project.ontology_id}-edit.owl",
        Path(project.local_path) / "ontology" / f"{project.ontology_id}-edit.owl",
        Path(project.odk_repo_path or "") / "src" / "ontology" / f"{project.ontology_id}-edit.owl",
        Path(project.odk_repo_path or "") / f"{project.ontology_id}-edit.owl",
    ]
    for p in edit_candidates:
        if p and p.exists() and p.is_file():
            return p, "edit_owl"

    return None, None


def _indexed_terms(session: Session, project_ref: str | int | None = None):
    project = None
    try:
        project = get_project(session, project_ref)
    except LookupError:
        pass

    if project:
        ontology_file, source_type = resolve_project_ontology_file(project)
        if ontology_file:
            return index_ontology_file(ontology_file)
        raise FileNotFoundError("No project ontology file found. Configure or build the project ontology first.")

    # Global/fallback logic if no active project is found
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
    public = {key: value for key, value in config.items() if key not in {"api_key", "inst_token"}}
    public["api_key"] = _masked_secret(config.get("api_key"))
    public["inst_token"] = _masked_secret(config.get("inst_token"))
    public["active"] = config.get("id") == active_id
    return public


def _upsert_saved_config(
    session: Session,
    *,
    kind: Literal["zotero", "llm", "publisher"],
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
        "api_key_env_var": values.get("api_key_env_var"),
        "temperature": values.get("temperature"),
        "max_output_tokens": values.get("max_output_tokens"),
        "timeout_seconds": values.get("timeout_seconds"),
        "retry_count": values.get("retry_count"),
        "stream": values.get("stream"),
        "inst_token": values.get("inst_token"),
        "enabled": values.get("enabled"),
        "extraction_mode": values.get("extraction_mode"),
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

    markdown_paper = _repository_markdown_for_source(source)
    creators = _json_loads(source.creators_json, [])
    creator_text = "; ".join(
        " ".join(filter(None, [creator.get("given"), creator.get("family")]))
        for creator in creators
        if isinstance(creator, dict)
    )
    markdown_text = None
    if markdown_paper is not None:
        include, reason = should_include_for_automatic_llm(markdown_paper)
        if not include:
            raise HTTPException(
                status_code=400,
                detail=f"Selected literature is excluded from automatic LLM extraction: {reason}",
            )
        markdown_text = markdown_paper.get("markdown")
    content = markdown_text or "\n\n".join(
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


def _clear_stored_literature(session: Session) -> None:
    """Clear literature storage rows and dependent extraction state after repository reset."""
    session.execute(delete(CandidateTermRecord))
    session.execute(delete(ExtractionRun))
    session.execute(delete(LiteratureDocument))
    session.execute(delete(LiteratureSource))
    session.commit()


def _repository_markdown_for_source(source: LiteratureSource) -> dict[str, Any] | None:
    result = load_llm_ready_repository_with_diagnostics()
    for paper in result.papers:
        metadata = paper.get("metadata") or {}
        if source.doi and str(metadata.get("doi") or paper.get("doi") or "").casefold() == source.doi.casefold():
            return paper
        if source.title and str(metadata.get("title") or paper.get("title") or "").casefold() == source.title.casefold():
            return paper
        if source.provider_item_key and source.provider_item_key.casefold() in str(metadata.get("id") or paper.get("id") or "").casefold():
            return paper
    return None


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
    api_key = payload.api_key or ""
    collection_key = payload.collection_key or ""
    base_url = payload.base_url or ""
    set_runtime_values(
        session,
        {
            "zotero_library_type": payload.library_type,
            "zotero_library_id": payload.library_id,
            "zotero_api_key": api_key,
            "zotero_collection_key": collection_key,
            "zotero_api_base_url": base_url,
        },
    )
    _upsert_saved_config(
        session,
        kind="zotero",
        values={
            "alias": f"Zotero {payload.library_type} {payload.library_id}",
            "library_type": payload.library_type,
            "library_id": payload.library_id,
            "api_key": api_key,
            "collection_key": collection_key,
            "base_url": base_url,
        },
    )
    return config_status(session)["zotero"]


@router.post("/config/llm")
def save_llm_config(
    payload: LlmConfigPayload,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    provider_key = normalize_provider_id(payload.provider) or payload.provider
    set_runtime_values(
        session,
        {
            "llm_provider": provider_key,
            "llm_api_key": payload.api_key,
            "llm_api_key_env_var": payload.api_key_env_var,
            "llm_model": payload.model,
            "llm_base_url": payload.base_url,
            "llm_temperature": str(payload.temperature) if payload.temperature is not None else None,
            "llm_max_output_tokens": str(payload.max_output_tokens) if payload.max_output_tokens is not None else None,
            "llm_timeout_seconds": str(payload.timeout_seconds) if payload.timeout_seconds is not None else None,
            "llm_retry_count": str(payload.retry_count) if payload.retry_count is not None else None,
            "llm_stream": str(bool(payload.stream)).lower() if payload.stream is not None else None,
        },
    )
    _upsert_saved_config(
        session,
        kind="llm",
        values={
            "alias": f"{provider_key} {payload.model or ''}".strip(),
            "provider": provider_key,
            "api_key": payload.api_key,
            "api_key_env_var": payload.api_key_env_var,
            "model": payload.model,
            "base_url": payload.base_url,
            "temperature": payload.temperature,
            "max_output_tokens": payload.max_output_tokens,
            "timeout_seconds": payload.timeout_seconds,
            "retry_count": payload.retry_count,
            "stream": payload.stream,
        },
    )
    return config_status(session)["llm"]


@router.get("/config/llm/providers")
def llm_provider_catalog() -> dict[str, Any]:
    return provider_catalog()


@router.post("/config/llm/test")
def test_configured_llm(session: Session = Depends(get_session)) -> dict[str, Any]:
    result = test_llm_connection(llm_config(session))
    return {
        "ok": result.ok,
        "provider": result.provider,
        "provider_key": result.provider_key,
        "model": result.model,
        "api_key_found": result.api_key_found,
        "api_key_source": result.api_key_source,
        "latency_ms": result.latency_ms,
        "status": result.status,
        "response_preview": result.response_preview,
        "error": result.error,
    }


@router.get("/diagnostics/docker-odk")
def docker_odk_diagnostics(session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    literature = literature_config(session)
    ontology_path = _configured_ontology_path(session)
    selected = _selected_ontology_file(session)
    tools = {
        "robot": shutil.which("robot"),
        "java": shutil.which("java"),
        "make": shutil.which("make"),
        "git": shutil.which("git"),
    }
    return {
        "docker": {
            "configured_for_container_paths": str(settings.odk_home).startswith("/"),
            "data_dir": str(literature.base_dir),
        },
        "tools": {name: {"available": bool(path), "path": path} for name, path in tools.items()},
        "odk": {
            "home": str(settings.odk_home),
            "home_exists": settings.odk_home.exists(),
            "ontology_repo": str(settings.ontology_repo) if settings.ontology_repo else None,
            "ontology_repo_exists": settings.ontology_repo.exists() if settings.ontology_repo else False,
            "ppo_odk_ontology_path": str(settings.ppo_odk_ontology_path),
            "ppo_odk_ontology_path_exists": settings.ppo_odk_ontology_path.exists(),
            "validation_command": settings.odk_validation_command,
        },
        "ontology": {
            "configured_path": str(ontology_path),
            "configured_path_exists": ontology_path.exists(),
            "selected_file": str(selected) if selected else None,
            "selected_file_exists": selected.exists() if selected else False,
        },
        "literature": {
            "base_dir": str(literature.base_dir),
            "base_dir_exists": literature.base_dir.exists(),
            "papers_dir": str(literature.papers_dir),
            "papers_dir_exists": literature.papers_dir.exists(),
            "combined_output_file": str(literature.combined_output_file),
            "combined_output_exists": literature.combined_output_file.exists(),
        },
    }


@router.get("/curation/prompt")
def read_curation_prompt(session: Session = Depends(get_session)) -> dict[str, Any]:
    setting = session.get(AppSetting, CURATION_PROMPT_SETTING_KEY)
    prompt = setting.value if setting is not None and setting.value else DEFAULT_CURATION_PROMPT
    return {
        "prompt": prompt,
        "default_prompt": DEFAULT_CURATION_PROMPT,
        "is_custom": bool(setting is not None and setting.value),
        "inputs": [
            "saved editable curation prompt",
            "selected existing ontology .obo file",
            "combined_literature.md",
        ],
    }


@router.post("/curation/prompt")
def save_curation_prompt(
    payload: CurationPromptPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    set_runtime_values(session, {CURATION_PROMPT_SETTING_KEY: payload.prompt})
    return {
        "prompt": payload.prompt,
        "default_prompt": DEFAULT_CURATION_PROMPT,
        "is_custom": payload.prompt != DEFAULT_CURATION_PROMPT,
    }


@router.delete("/curation/prompt")
def reset_curation_prompt(session: Session = Depends(get_session)) -> dict[str, Any]:
    setting = session.get(AppSetting, CURATION_PROMPT_SETTING_KEY)
    if setting is not None:
        session.delete(setting)
        session.commit()
    return {
        "prompt": DEFAULT_CURATION_PROMPT,
        "default_prompt": DEFAULT_CURATION_PROMPT,
        "is_custom": False,
    }


@router.get("/config/saved")
def list_saved_api_configs(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    active_ids = {
        "zotero": _active_config_id(session, "zotero"),
        "llm": _active_config_id(session, "llm"),
        "publisher": _active_config_id(session, "publisher"),
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
    values = payload.model_dump()
    if payload.kind == "llm":
        values["provider"] = normalize_provider_id(values.get("provider")) or values.get("provider")
    config = _upsert_saved_config(session, kind=payload.kind, values=values)
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
        provider_key = normalize_provider_id(config.get("provider")) or config.get("provider")
        set_runtime_values(
            session,
            {
                "llm_provider": provider_key,
                "llm_api_key": config.get("api_key"),
                "llm_api_key_env_var": config.get("api_key_env_var"),
                "llm_model": config.get("model"),
                "llm_base_url": config.get("base_url"),
                "llm_temperature": str(config.get("temperature")) if config.get("temperature") is not None else None,
                "llm_max_output_tokens": str(config.get("max_output_tokens")) if config.get("max_output_tokens") is not None else None,
                "llm_timeout_seconds": str(config.get("timeout_seconds")) if config.get("timeout_seconds") is not None else None,
                "llm_retry_count": str(config.get("retry_count")) if config.get("retry_count") is not None else None,
                "llm_stream": str(bool(config.get("stream"))).lower() if config.get("stream") is not None else None,
                "active_llm_config_id": config_id,
            },
        )
    elif kind == "publisher":
        set_runtime_values(
            session,
            {
                "elsevier_api_key": config.get("api_key"),
                "elsevier_inst_token": config.get("inst_token"),
                "elsevier_api_base_url": config.get("base_url"),
                "publisher_api_enrichment_enabled": str(bool(config.get("enabled"))).lower(),
                "literature_extraction_mode": config.get("extraction_mode") or "publisher_api_required",
                "active_publisher_config_id": config_id,
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


@router.post("/config/literature")
def save_literature_config(
    payload: LiteraturePipelineConfigPayload,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    values: dict[str, str | None] = {}
    if payload.zotero_literature_storage_path is not None:
        values["zotero_literature_storage_path"] = payload.zotero_literature_storage_path
    hidden_path_overrides = [
        "literature_base_dir",
        "literature_pdf_dir",
        "literature_generated_md_dir",
        "literature_repository_path",
        "literature_combined_output_file",
        "literature_fuzzy_min_score",
    ]
    session.execute(delete(AppSetting).where(AppSetting.key.in_(hidden_path_overrides)))
    session.commit()
    set_runtime_values(session, values)
    literature = config_status(session)["literature"]
    return literature


@router.post("/config/publisher")
def save_publisher_config(payload: PublisherConfigPayload, session: Session = Depends(get_session)) -> dict[str, object]:
    values: dict[str, str | None] = {}
    if payload.elsevier_api_key is not None:
        values["elsevier_api_key"] = payload.elsevier_api_key
    if payload.elsevier_inst_token is not None:
        values["elsevier_inst_token"] = payload.elsevier_inst_token
    if payload.elsevier_api_base_url is not None:
        values["elsevier_api_base_url"] = payload.elsevier_api_base_url
    if payload.publisher_api_enrichment_enabled is not None:
        values["publisher_api_enrichment_enabled"] = str(payload.publisher_api_enrichment_enabled).lower()
    if payload.literature_extraction_mode is not None:
        values["literature_extraction_mode"] = payload.literature_extraction_mode
    set_runtime_values(session, values)
    config = publisher_config(session)
    active_id = _active_config_id(session, "publisher")
    existing = next((item for item in _saved_configs(session) if item.get("id") == active_id), None)
    saved = _upsert_saved_config(
        session,
        kind="publisher",
        values={
            "id": active_id,
            "created_at": existing.get("created_at") if existing else None,
            "alias": "Elsevier Publisher API",
            "provider": "elsevier",
            "base_url": config.base_url,
            "api_key": payload.elsevier_api_key if payload.elsevier_api_key is not None else (existing or {}).get("api_key"),
            "inst_token": payload.elsevier_inst_token if payload.elsevier_inst_token is not None else (existing or {}).get("inst_token"),
            "enabled": config.enabled,
            "extraction_mode": config.extraction_mode,
        },
    )
    return {
        "configured": bool(config.api_key),
        "enabled": config.enabled,
        "base_url": config.base_url,
        "api_key": "configured" if config.api_key else "missing",
        "inst_token": "configured" if config.inst_token else "missing",
        "api_key_source": config.api_key_source,
        "literature_extraction_mode": config.extraction_mode,
        "pdf_fallback_enabled": config.extraction_mode == "pdf_fallback_allowed",
        "saved_config_id": saved["id"],
    }


def _canonical_project_paths(session: Session, project_ref: str | int | None = None) -> tuple[Project, RepositoryPaths]:
    project = get_project(session, project_ref)
    root = Path(project.literature_repository_path or (Path(project.local_path) / "literature"))
    return project, RepositoryPaths.from_root(root)


def _save_import_diagnostics(session: Session, report: dict[str, Any]) -> None:
    set_runtime_values(session, {"literature_last_import_diagnostics": json.dumps(report, ensure_ascii=False)})


def _import_diagnostics_payload(session: Session) -> dict[str, Any]:
    publisher = publisher_config(session)
    zotero = zotero_config(session)
    setting = session.get(AppSetting, "literature_last_import_diagnostics")
    try:
        last_import = json.loads(setting.value) if setting else None
    except json.JSONDecodeError:
        last_import = None
    return {
        "extraction_mode": publisher.extraction_mode,
        "elsevier_api_configured": bool(publisher.api_key),
        "zotero_configured": bool(zotero.library_type and zotero.library_id),
        "pdf_fallback_enabled": publisher.extraction_mode == "pdf_fallback_allowed",
        "last_import": last_import,
    }


@router.get("/literature/import-diagnostics")
def literature_import_diagnostics(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _import_diagnostics_payload(session)


@router.post("/literature/test-publisher-api")
def test_literature_publisher_api(payload: PublisherApiTestPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    if not payload.doi and not payload.pii and not payload.sciencedirect_url:
        raise HTTPException(status_code=400, detail="Provide a DOI, PII, or ScienceDirect URL.")
    _, paths = _canonical_project_paths(session, payload.project)
    publisher = publisher_config(session)
    try:
        return run_publisher_api_test(
            paths,
            LiteratureIdentification(doi=payload.doi, pii=payload.pii, sciencedirect_url=payload.sciencedirect_url),
            publisher=ElsevierApiConfig(api_key=publisher.api_key, inst_token=publisher.inst_token, base_url=publisher.base_url, enabled=publisher.enabled),
            write_artifacts=payload.write_artifacts,
        )
    except LiteratureExtractionError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "diagnostics": exc.diagnostics}) from exc


def _canonical_entry_payload(item: dict[str, Any]) -> dict[str, Any]:
    markdown = Path(item["markdown_file"]).read_text(encoding="utf-8", errors="replace") if item.get("markdown_file") else None
    return {
        "id": item["canonical_id"],
        "repository_stage": item.get("repository_stage") or "staged",
        "provider": item.get("source_type") or "canonical_pipeline",
        "title": item.get("title"),
        "authors": item.get("authors") or [],
        "year": item.get("year"),
        "journal": item.get("journal"),
        "pii": item.get("pii"),
        "doi": item.get("doi"),
        "source_type": item.get("source_type"),
        "import_status": item.get("import_status"),
        "duplicate_status": item.get("duplicate_status"),
        "curation_status": item.get("curation_status"),
        "pipeline_version": item.get("pipeline_version"),
        "metadata_source": item.get("metadata_source"),
        "content_source": item.get("content_source"),
        "extraction_mode": item.get("extraction_mode"),
        "used_api_provider": item.get("used_api_provider"),
        "doi_used": item.get("doi_used"),
        "pii_used": item.get("pii_used"),
        "xml_retrieved": bool(item.get("xml_retrieved")),
        "pdf_used": bool(item.get("pdf_used")),
        "fallback_used": bool(item.get("fallback_used")),
        "fallback_authorized_by": item.get("fallback_authorized_by"),
        "extraction_status": item.get("extraction_status"),
        "extraction_errors": item.get("extraction_errors") or [],
        "generated_artifacts": item.get("generated_artifacts") or [],
        "extraction_warnings": item.get("extraction_warnings") or [],
        "api_retrieval_status": item.get("api_retrieval_status"),
        "crossref_retrieval_status": item.get("crossref_retrieval_status"),
        "lookup_doi": item.get("lookup_doi"),
        "lookup_pii": item.get("lookup_pii"),
        "xml_artifact_path": item.get("xml_artifact_path"),
        "xml_markdown_artifact_path": item.get("xml_markdown_artifact_path"),
        "pdf_fallback_markdown_path": item.get("pdf_fallback_markdown_path"),
        "imported_at": item.get("imported_at") or item.get("created_at"),
        "staged_entry_id": item.get("staged_entry_id"),
        "markdown_available": item.get("markdown_available"),
        "markdown_file": item.get("markdown_file"),
        "literature_markdown": markdown,
        "clean_markdown": markdown,
        "llm_context_markdown": markdown,
        "full_text": markdown,
        "content": {"sections": [], "canonical_source": "canonical_pipeline"},
        "creators": [], "project_tags": item.get("project_tags") or [],
        "literature_status": {
            "state": item.get("state") or "ready_for_llm",
            "source_type": item.get("source_type"),
            "import_status": item.get("import_status"),
            "duplicate_status": item.get("duplicate_status"),
            "markdown_source_file": item.get("markdown_file"),
            "has_markdown": bool(item.get("markdown_file")),
            "metadata_source": item.get("metadata_source"),
            "content_source": item.get("content_source"),
            "extraction_mode": item.get("extraction_mode"),
            "pdf_used": bool(item.get("pdf_used")),
            "fallback_used": bool(item.get("fallback_used")),
            "extraction_warnings": item.get("extraction_warnings") or [],
            "api_retrieval_status": item.get("api_retrieval_status"),
            "crossref_retrieval_status": item.get("crossref_retrieval_status"),
        },
    }


@router.get("/literature/canonical")
def list_canonical_literature(project: str | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    selected, paths = _canonical_project_paths(session, project)
    staged = [_canonical_entry_payload(item) for item in list_canonical_entries(paths)]
    curated = [_canonical_entry_payload(item) for item in list_curated_entries(paths)]
    return {"project": selected.slug, "repository": str(paths.root), "entries": curated, "staged_entries": staged, "curated_entries": curated, "combined_output_file": str(paths.combined)}


@router.get("/literature/staged/{entry_id}")
def read_staged_literature(entry_id: str, project: str | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    _, paths = _canonical_project_paths(session, project)
    item = next((entry for entry in list_canonical_entries(paths) if entry.get("canonical_id") == entry_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Staged literature entry not found")
    return _canonical_entry_payload(item)


@router.patch("/literature/staged/{entry_id}")
def edit_staged_literature(entry_id: str, payload: LiteratureEntryEditPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    _, paths = _canonical_project_paths(session, payload.project)
    try:
        return _canonical_entry_payload(update_staged_entry(paths, entry_id, metadata=payload.metadata, markdown=payload.markdown, project_tags=payload.project_tags))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/literature/staged/{entry_id}/promote")
def promote_staged_literature(entry_id: str, payload: StagedLiteratureDecisionPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    _, paths = _canonical_project_paths(session, payload.project)
    try:
        item = promote_staged_entry(paths, entry_id, metadata=payload.metadata, markdown=payload.markdown, project_tags=payload.project_tags)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "entry": _canonical_entry_payload(item), "combined_output_file": str(paths.combined)}


@router.post("/literature/staged/{entry_id}/reject")
def reject_staged_literature(entry_id: str, payload: StagedLiteratureDecisionPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    _, paths = _canonical_project_paths(session, payload.project)
    if payload.delete and not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required to delete a staged entry.")
    try:
        return {"ok": True, **reject_staged_entry(paths, entry_id, delete=payload.delete)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/literature/curated/{entry_id}")
def read_curated_literature(entry_id: str, project: str | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    _, paths = _canonical_project_paths(session, project)
    item = next((entry for entry in list_curated_entries(paths) if entry.get("canonical_id") == entry_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Curated literature entry not found")
    return _canonical_entry_payload(item)


@router.patch("/literature/curated/{entry_id}")
def edit_curated_literature(entry_id: str, payload: LiteratureEntryEditPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    _, paths = _canonical_project_paths(session, payload.project)
    try:
        return _canonical_entry_payload(update_curated_entry(paths, entry_id, metadata=payload.metadata, markdown=payload.markdown, project_tags=payload.project_tags))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/literature/cleanup-staged")
def cleanup_staged_literature(payload: CanonicalLiteratureActionPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    if not payload.dry_run and not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required to delete uncurated imported literature.")
    project, paths = _canonical_project_paths(session, payload.project)
    repositories = [
        {"repository": str(paths.root), **cleanup_unpromoted_staged(paths, dry_run=payload.dry_run)}
    ]
    legacy_root = literature_config(session).base_dir
    if legacy_root.resolve() != paths.root.resolve() and legacy_root.exists():
        legacy_paths = RepositoryPaths.from_root(legacy_root)
        repositories.append(
            {"repository": str(legacy_paths.root), **cleanup_unpromoted_staged(legacy_paths, dry_run=payload.dry_run)}
        )
    sum_keys = (
        "deleted_count", "files_deleted_count", "orphan_files_deleted_count",
        "files_skipped_curated", "files_skipped_external", "files_missing",
        "directories_cleaned_count", "curated_count",
    )
    totals = {key: sum(int(report.get(key, 0)) for report in repositories) for key in sum_keys}
    return {
        "ok": True,
        "project": project.slug,
        "dry_run": payload.dry_run,
        **totals,
        "combined_removed": any(bool(report.get("combined_removed")) for report in repositories),
        "deleted_ids": [entry_id for report in repositories for entry_id in report.get("deleted_ids", [])],
        "files_deleted": [f"{report['repository']}::{path}" for report in repositories for path in report.get("files_deleted", [])],
        "directories_cleaned": [f"{report['repository']}::{path}" for report in repositories for path in report.get("directories_cleaned", [])],
        "errors": [error for report in repositories for error in report.get("errors", [])],
        "repositories": repositories,
    }


@router.post("/literature/import")
def import_canonical_literature(payload: CanonicalLiteratureImportPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, paths = _canonical_project_paths(session, payload.project)
    publisher = publisher_config(session)
    extraction_mode = "pdf_fallback_allowed" if payload.allow_pdf_fallback else (payload.extraction_mode or publisher.extraction_mode or DEFAULT_EXTRACTION_MODE)
    api_config = ElsevierApiConfig(api_key=publisher.api_key, inst_token=publisher.inst_token, base_url=publisher.base_url, enabled=publisher.enabled)
    if payload.local_pdf_path or payload.doi or payload.pii or payload.sciencedirect_url:
        try:
            entry, duplicate = import_identified_item(
                paths,
                LiteratureIdentification(
                    zotero_key=payload.zotero_key,
                    doi=payload.doi,
                    pii=payload.pii,
                    sciencedirect_url=payload.sciencedirect_url,
                    title=payload.title,
                    authors=payload.authors,
                    year=payload.year,
                    journal=payload.journal,
                    pdf_path=payload.local_pdf_path,
                    metadata_source="zotero" if payload.zotero_key else "manual",
                ),
                publisher=api_config,
                extraction_mode=extraction_mode,
                keep_sources=payload.keep_sources,
                overwrite=payload.overwrite,
            )
        except LiteratureExtractionError as exc:
            report = {**exc.diagnostics, "last_import_status": "failed", "items_imported_through_xml": 0, "api_failures": 1, "pdf_fallbacks": 0}
            _save_import_diagnostics(session, report)
            raise HTTPException(status_code=400, detail={"message": str(exc), "diagnostics": report}) from exc
        except (OSError, ValueError) as exc:
            report = {"extraction_mode": extraction_mode, "last_import_status": "failed", "items_imported_through_xml": 0, "api_failures": 1, "pdf_fallbacks": 0, "extraction_errors": [str(exc)]}
            _save_import_diagnostics(session, report)
            raise HTTPException(status_code=400, detail={"message": str(exc), "diagnostics": report}) from exc
        report = {"extraction_mode": extraction_mode, "last_import_status": "success", "items_imported_through_xml": int(entry.get("xml_retrieved", False)), "api_failures": 0, "pdf_fallbacks": int(entry.get("fallback_used", False)), "content_source": entry.get("content_source"), "pdf_used": bool(entry.get("pdf_used")), "fallback_used": bool(entry.get("fallback_used")), "api_retrieval_status": entry.get("api_retrieval_status"), "extraction_errors": entry.get("extraction_errors") or []}
        _save_import_diagnostics(session, report)
        return {"ok": True, "project": project.slug, "files_scanned": 1, "imported": int(not duplicate), "duplicates": int(duplicate), "failed": 0, "entry": _canonical_entry_payload(entry), "combined_count": build_canonical_combined(paths), "combined_output_file": str(paths.combined)}
    source_value = payload.zotero_storage or payload.pdf_dir
    if not source_value:
        settings: dict[str, Any] = {}
        source_config = paths.root / "source_config.json"
        if source_config.exists():
            settings = json.loads(source_config.read_text(encoding="utf-8"))
        source_value = settings.get("source_path")
    if not source_value:
        raise HTTPException(status_code=400, detail="Provide zotero_storage or pdf_dir for the active project.")
    source_type = "zotero_storage" if payload.zotero_storage else "local_pdf_folder"
    xml_imported = 0
    failures: list[dict[str, Any]] = []
    source_records = []
    if source_type == "zotero_storage" and extraction_mode != "pdf_only":
        source_records = session.scalars(select(LiteratureSource).where((LiteratureSource.project_id.is_(None)) | (LiteratureSource.project_id == project.id))).all()
        for source in source_records:
            try:
                creators_data = json.loads(source.creators_json or "[]")
            except json.JSONDecodeError:
                creators_data = []
            creators = [" ".join(str(creator.get(key) or "").strip() for key in ("given", "family")).strip() for creator in creators_data if isinstance(creator, dict)]
            try:
                entry, _ = import_identified_item(
                    paths,
                    LiteratureIdentification(
                        zotero_key=source.provider_item_key,
                        doi=source.doi,
                        sciencedirect_url=source.url,
                        title=source.title,
                        authors=[creator for creator in creators if creator],
                        year=source.year,
                        pdf_path=None,
                        metadata_source="zotero",
                        identifier_metadata=_json_loads(source.identifiers_json, {}),
                    ),
                    publisher=api_config,
                    extraction_mode="publisher_api_required",
                    keep_sources=payload.keep_sources,
                    overwrite=payload.overwrite,
                )
                xml_imported += int(entry.get("xml_retrieved", False))
            except LiteratureExtractionError as exc:
                failures.append({"zotero_key": source.provider_item_key, "title": source.title, "message": str(exc), "diagnostics": exc.diagnostics})

    if source_type == "zotero_storage" and extraction_mode == "publisher_api_required":
        if not source_records:
            message = "No synced Zotero literature identifiers are available. Sync Zotero first; PDFs are not inspected in publisher_api_required mode."
            failures.append({"message": message, "diagnostics": {"extraction_mode": extraction_mode, "pdf_used": False, "fallback_used": False}})
        report = {"extraction_mode": extraction_mode, "last_import_status": "failed" if failures else "success", "items_imported_through_xml": xml_imported, "api_failures": len(failures), "pdf_fallbacks": 0, "pdf_used": False, "fallback_used": False, "extraction_errors": [failure["message"] for failure in failures]}
        _save_import_diagnostics(session, report)
        if failures:
            raise HTTPException(status_code=400, detail={"message": failures[0]["message"], "diagnostics": report, "failures": failures})
        write_project_settings(paths, zotero_storage_path=payload.zotero_storage, literature_source_directory=source_value, keep_temporary_pdfs=False, overwrite_existing_markdown=payload.overwrite, preserve_curated_metadata=True)
        return {"ok": True, "project": project.slug, "extraction_mode": extraction_mode, "files_scanned": len(source_records), "imported": xml_imported, "duplicates": len(source_records) - xml_imported, "failed": 0, "xml_imported": xml_imported, "pdf_used": False, "fallback_used": False, "combined_count": build_canonical_combined(paths), "combined_output_file": str(paths.combined), "failures": []}
    try:
        result = import_canonical_directory(paths, Path(source_value), source_type=source_type, extraction_mode=extraction_mode, keep_sources=payload.keep_sources, overwrite=payload.overwrite)
        write_project_settings(paths, zotero_storage_path=payload.zotero_storage, literature_source_directory=source_value, keep_temporary_pdfs=payload.keep_sources, overwrite_existing_markdown=payload.overwrite, preserve_curated_metadata=True)
    except LiteratureExtractionError as exc:
        report = {**exc.diagnostics, "last_import_status": "failed", "items_imported_through_xml": xml_imported, "api_failures": len(failures), "pdf_fallbacks": 0}
        _save_import_diagnostics(session, report)
        raise HTTPException(status_code=400, detail={"message": str(exc), "diagnostics": report}) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    report = {"extraction_mode": extraction_mode, "last_import_status": "success" if not result.failed else "partial_failure", "items_imported_through_xml": xml_imported, "api_failures": len(failures), "pdf_fallbacks": result.imported + result.duplicates if extraction_mode == "pdf_fallback_allowed" else 0, "pdf_used": True, "fallback_used": extraction_mode == "pdf_fallback_allowed", "extraction_errors": [failure["error"] for failure in (result.failures or [])]}
    _save_import_diagnostics(session, report)
    return {"ok": True, "project": project.slug, "extraction_mode": extraction_mode, "xml_imported": xml_imported, "pdf_used": True, "fallback_used": extraction_mode == "pdf_fallback_allowed", **result.to_dict()}


@router.post("/literature/build-combined")
def build_canonical_literature(payload: CanonicalLiteratureActionPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, paths = _canonical_project_paths(session, payload.project)
    return {"ok": True, "project": project.slug, "count": build_canonical_combined(paths), "combined_output_file": str(paths.combined)}


@router.post("/literature/deduplicate")
def deduplicate_canonical_literature(payload: CanonicalLiteratureActionPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    if payload.apply and not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required to apply deduplication.")
    project, paths = _canonical_project_paths(session, payload.project)
    return {"ok": True, "project": project.slug, **deduplicate_canonical(paths, apply=payload.apply)}


@router.post("/literature/migrate-old")
def migrate_canonical_literature(payload: CanonicalLiteratureActionPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, paths = _canonical_project_paths(session, payload.project)
    return {"ok": True, "project": project.slug, **migrate_old_literature(paths, apply=payload.apply)}


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
    refresh_literature_markdown_repository(session)
    return {"id": document.id, "filename": document.filename}


@router.get("/literature/repository/status")
def literature_repository_status() -> dict[str, Any]:
    return repository_status()


@router.post("/literature/repository/reset")
def reset_literature_repository_action(
    payload: LiteratureResetPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required to reset literature.")
    try:
        project, paths = _canonical_project_paths(session)
    except LookupError:
        result = reset_literature_repository()
        if not result.ok:
            raise HTTPException(status_code=500, detail=result.message)
        _clear_stored_literature(session)
        return {"ok": result.ok, "path": str(result.path), "deleted": result.deleted, "message": result.message}
    try:
        result = reset_canonical_repository(paths)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "project": project.slug, "message": "Active project literature repository reset."}


@router.post("/literature/pipeline/run")
def run_literature_pipeline_action(session: Session = Depends(get_session)) -> dict[str, Any]:
    config = literature_pipeline_config(session)
    project = None
    try:
        project, paths = _canonical_project_paths(session)
        config = type(config)(zotero_literature_storage_path=config.zotero_literature_storage_path, base_dir=paths.root, pdf_dir=paths.sources, generated_md_dir=paths.markdown, papers_dir=paths.markdown, combined_output_file=paths.combined, fuzzy_min_score=config.fuzzy_min_score, extraction_mode=config.extraction_mode)
    except LookupError:
        pass
    try:
        result = run_literature_pipeline(config)
    except (FileNotFoundError, ImportError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "project": project.slug if project else None,
        "combined_output_file": str(result.combined_output_file),
        "combined_output_exists": result.combined_output_file.exists(),
        "copied_pdf_count": result.copied_pdf_count,
        "converted_markdown_count": result.converted_markdown_count,
        "failed_pdf_count": result.failed_pdf_count,
        "created_paper_markdown_count": result.created_paper_markdown_count,
        "structured_markdown_count": result.structured_markdown_count,
        "combined_markdown_count": result.combined_markdown_count,
        "skipped_paper_count": result.skipped_paper_count,
        "extraction_report_file": str(result.extraction_report_file) if result.extraction_report_file else None,
        "extraction_report_exists": bool(result.extraction_report_file and result.extraction_report_file.exists()),
        "cleanup_report_file": str(result.cleanup_report_file) if result.cleanup_report_file else None,
        "cleanup_report_exists": bool(result.cleanup_report_file and result.cleanup_report_file.exists()),
        "repository_status": repository_status(config.papers_dir),
    }


def _zotero_link_payload(source: LiteratureSource, session: Session) -> dict[str, Any]:
    config = zotero_config(session)
    duplicate = False
    if source.provider_item_key:
        duplicate = session.scalar(
            select(LiteratureSource.id)
            .where(
                LiteratureSource.provider == "zotero",
                LiteratureSource.provider_item_key == source.provider_item_key,
                LiteratureSource.id != source.id,
            )
            .limit(1)
        ) is not None
    uri, diagnostics = zotero_select_uri(
        source.provider_item_key,
        library_type=config.library_type,
        library_id=config.library_id,
        duplicate=duplicate,
    )
    return {
        "item_key": source.provider_item_key if is_valid_zotero_item_key(source.provider_item_key) else None,
        "uri": uri,
        "library_id": config.library_id,
        "diagnostics": diagnostics,
    }


def _document_attachment_payload(document: LiteratureDocument) -> dict[str, Any]:
    return {
        "filename": document.filename,
        "path": document.path,
        "mime_type": {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".tsv": "text/tab-separated-values",
            ".csv": "text/csv",
        }.get(document.suffix),
        "text_extracted": bool(document.content),
    }


def _source_text_payload(source: LiteratureSource, session: Session) -> dict[str, Any]:
    documents = session.scalars(
        select(LiteratureDocument)
        .where(LiteratureDocument.source_id == source.id)
        .order_by(LiteratureDocument.id)
    ).all()
    text_parts = [document.content.strip() for document in documents if document.content and document.content.strip()]
    sections = [
        {
            "heading": document.filename,
            "text": document.content.strip(),
            "page_start": None,
            "page_end": None,
        }
        for document in documents
        if document.content and document.content.strip()
    ]
    quality_flags = []
    if not source.title:
        quality_flags.append("missing_title")
    if not documents:
        quality_flags.append("missing_attachment")
    if not text_parts and not source.abstract:
        quality_flags.append("missing_full_text")
    for document in documents:
        if document.suffix == ".pdf" and not document.content:
            quality_flags.append("possible_scanned_pdf")
    return {
        "full_text": "\n\n".join(text_parts) if text_parts else None,
        "sections": sections,
        "attachments": [_document_attachment_payload(document) for document in documents],
        "source_file": documents[0].path if documents else None,
        "quality_flags": sorted(set(quality_flags)),
    }


def _source_payload(source: LiteratureSource, session: Session) -> dict[str, Any]:
    text_payload = _source_text_payload(source, session)
    zotero = _zotero_link_payload(source, session)
    markdown_paper = _repository_markdown_for_source(source)
    markdown_metadata = (markdown_paper or {}).get("metadata") or {}
    markdown_file = (markdown_paper or {}).get("source_file")
    content = {
        "sections": (markdown_paper or {}).get("sections") or text_payload["sections"],
        "canonical_source": "markdown_repository" if markdown_paper else "database_metadata",
    }
    review_status = _literature_review_status(markdown_paper or {})
    return {
        "id": source.id,
        "provider": source.provider,
        "provider_item_key": source.provider_item_key,
        "citation_key": source.citation_key,
        "title": markdown_metadata.get("title") or source.title,
        "creators": _json_loads(source.creators_json, []),
        "authors": markdown_metadata.get("authors") or [],
        "year": markdown_metadata.get("year") or source.year,
        "doi": markdown_metadata.get("doi") or source.doi,
        "url": markdown_metadata.get("url") or source.url,
        "abstract": (markdown_paper or {}).get("abstract") or source.abstract,
        "tags": _json_loads(source.tags_json, []),
        "project_tags": _json_loads(source.project_tags_json, []),
        "collections": _json_loads(source.collections_json, []),
        "item_type": source.item_type,
        "publication_venue": source.item_type,
        "zotero": zotero,
        "zotero_select_uri": zotero.get("uri"),
        "synced_at": source.synced_at.isoformat() if source.synced_at else None,
        "full_text": (markdown_paper or {}).get("markdown") or text_payload["full_text"],
        "sections": content["sections"],
        "content": content,
        "content_preview": (markdown_paper or {}).get("markdown") or text_payload["full_text"],
        "attachments": text_payload["attachments"],
        "source_file": text_payload["source_file"],
        "quality_flags": text_payload["quality_flags"],
        "markdown_file": markdown_file,
        "literature_markdown": (markdown_paper or {}).get("markdown"),
        "raw_markdown": (markdown_paper or {}).get("raw_markdown_text"),
        "clean_markdown": (markdown_paper or {}).get("clean_markdown"),
        "llm_context_markdown": (markdown_paper or {}).get("llm_context_markdown"),
        "literature_metadata": markdown_metadata or None,
        "literature_review": review_status,
        "literature_status": {
            "markdown_source_file": markdown_file,
            "section_count": len(content["sections"] or []),
            "has_markdown": markdown_paper is not None,
            **review_status,
        },
    }


def _repository_paper_payload(paper: dict[str, Any], index: int) -> dict[str, Any]:
    metadata = paper.get("metadata") or {}
    markdown_file = paper.get("source_file")
    sections = paper.get("sections") or []
    title = metadata.get("title") or paper.get("title") or Path(str(markdown_file or "")).stem
    review_status = _literature_review_status(paper)
    return {
        "id": f"markdown-{index}",
        "provider": "markdown_repository",
        "provider_item_key": None,
        "citation_key": None,
        "title": title,
        "creators": [],
        "authors": metadata.get("authors") or [],
        "year": metadata.get("year") or paper.get("year"),
        "doi": metadata.get("doi") or paper.get("doi"),
        "url": metadata.get("url") or paper.get("url"),
        "abstract": paper.get("abstract"),
        "tags": [],
        "project_tags": [],
        "collections": [],
        "item_type": "markdown",
        "publication_venue": "Markdown repository",
        "zotero": {"item_key": None, "uri": None, "library_id": None, "diagnostics": ["repository_only"]},
        "zotero_select_uri": None,
        "synced_at": None,
        "full_text": paper.get("markdown"),
        "sections": sections,
        "content": {
            "sections": sections,
            "canonical_source": "markdown_repository",
        },
        "content_preview": paper.get("markdown"),
        "attachments": [],
        "source_file": markdown_file,
        "quality_flags": [],
        "markdown_file": markdown_file,
        "literature_markdown": paper.get("markdown"),
        "raw_markdown": paper.get("raw_markdown_text"),
        "clean_markdown": paper.get("clean_markdown"),
        "llm_context_markdown": paper.get("llm_context_markdown"),
        "literature_metadata": metadata or None,
        "literature_review": review_status,
        "literature_status": {
            "markdown_source_file": markdown_file,
            "section_count": len(sections),
            "has_markdown": True,
            **review_status,
        },
    }


def _literature_review_status(paper: dict[str, Any]) -> dict[str, Any]:
    include, reason = should_include_for_automatic_llm(paper)
    return {
        "metadata_title": paper.get("metadata_title") or (paper.get("metadata") or {}).get("metadata_title"),
        "detected_title": paper.get("detected_title") or (paper.get("metadata") or {}).get("detected_title"),
        "title_similarity_score": paper.get("title_similarity_score")
        or (paper.get("metadata") or {}).get("title_similarity_score"),
        "metadata_match_status": paper.get("metadata_match_status")
        or (paper.get("metadata") or {}).get("metadata_match_status")
        or "unknown",
        "document_role": paper.get("document_role") or (paper.get("metadata") or {}).get("document_role") or "unknown",
        "extraction_quality": paper.get("extraction_quality")
        or (paper.get("metadata") or {}).get("extraction_quality")
        or "unknown",
        "state": paper.get("state") or (paper.get("metadata") or {}).get("state") or "unknown",
        "zotero_title": paper.get("zotero_title") or (paper.get("metadata") or {}).get("zotero_title"),
        "zotero_doi": paper.get("zotero_doi") or (paper.get("metadata") or {}).get("zotero_doi"),
        "detected_doi": paper.get("detected_doi") or (paper.get("metadata") or {}).get("detected_doi"),
        "doi_match_status": paper.get("doi_match_status") or (paper.get("metadata") or {}).get("doi_match_status"),
        "extraction_engine_used": paper.get("extraction_engine_used")
        or (paper.get("metadata") or {}).get("extraction_engine_used"),
        "page_count_pdf": paper.get("page_count_pdf") or (paper.get("metadata") or {}).get("page_count_pdf"),
        "page_count_extracted": paper.get("page_count_extracted")
        or (paper.get("metadata") or {}).get("page_count_extracted"),
        "word_count": paper.get("word_count") or (paper.get("metadata") or {}).get("word_count"),
        "warnings": paper.get("warnings") or (paper.get("metadata") or {}).get("warnings") or [],
        "requires_manual_review": bool(paper.get("requires_manual_review")),
        "exclude_from_automatic_llm_extraction": bool(paper.get("exclude_from_automatic_llm_extraction")),
        "include_in_llm_extraction": bool(paper.get("include_in_llm_extraction", include)),
        "included_in_automatic_llm_extraction": include,
        "automatic_llm_exclusion_reason": reason,
        "raw_markdown_file": paper.get("raw_markdown_file") or (paper.get("metadata") or {}).get("raw_markdown_file"),
        "clean_markdown_file": paper.get("clean_markdown_file") or (paper.get("metadata") or {}).get("clean_markdown_file"),
        "llm_context_file": paper.get("llm_context_file") or (paper.get("metadata") or {}).get("llm_context_file"),
        "metadata_report_file": paper.get("metadata_report_file") or (paper.get("metadata") or {}).get("metadata_report_file"),
    }


@router.get("/zotero/entries")
def list_zotero_entries(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    sources = session.scalars(
        select(LiteratureSource)
        .where(LiteratureSource.provider == "zotero")
        .order_by(LiteratureSource.id)
    ).all()
    entries = [_source_payload(source, session) for source in sources]
    matched_markdown_files = {
        entry["markdown_file"]
        for entry in entries
        if entry.get("markdown_file")
    }
    repository_result = load_llm_ready_repository_with_diagnostics()
    for index, paper in enumerate(repository_result.papers, start=1):
        if paper.get("source_file") in matched_markdown_files:
            continue
        entries.append(_repository_paper_payload(paper, index))
    try:
        _, canonical_paths = _canonical_project_paths(session)
        canonical_files = {entry.get("markdown_file") for entry in entries}
        entries.extend(
            _canonical_entry_payload(item)
            for item in list_canonical_entries(canonical_paths)
            if item.get("markdown_file") not in canonical_files
        )
    except LookupError:
        canonical_paths = RepositoryPaths.from_root(Path(get_settings().literature_base_dir))
        canonical_files = {entry.get("markdown_file") for entry in entries}
        entries.extend(_canonical_entry_payload(item) for item in list_canonical_entries(canonical_paths) if item.get("markdown_file") not in canonical_files)
    return entries


@router.get("/zotero/entries/{source_id}")
def read_zotero_entry(source_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    source = session.get(LiteratureSource, source_id)
    if source is None or source.provider != "zotero":
        raise HTTPException(status_code=404, detail="Zotero entry not found")
    return _source_payload(source, session)


@router.patch("/zotero/entries/{source_id}/project-tags")
def update_zotero_entry_project_tags(
    source_id: int,
    payload: LiteratureProjectTagsPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    source = session.get(LiteratureSource, source_id)
    if source is None or source.provider != "zotero":
        raise HTTPException(status_code=404, detail="Zotero entry not found")
    source.project_tags_json = json.dumps(_clean_string_list(payload.project_tags))
    session.commit()
    session.refresh(source)
    return _source_payload(source, session)


@router.patch("/literature/repository/review")
def update_literature_repository_review(
    payload: LiteratureReviewUpdatePayload,
) -> dict[str, Any]:
    try:
        paper = update_literature_review_metadata(
            Path(payload.markdown_file),
            include_in_llm_extraction=payload.include_in_llm_extraction,
            metadata_match_status=payload.metadata_match_status,
            document_role=payload.document_role,
            requires_manual_review=payload.requires_manual_review,
            state=payload.state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "paper": {
            "title": paper.get("title"),
            "markdown_file": paper.get("source_file") or payload.markdown_file,
            "literature_review": _literature_review_status(paper),
        },
    }


@router.get("/literature/doctor")
def literature_doctor() -> dict[str, Any]:
    return {"ok": True, "extractors": extractor_availability().to_dict()}


@router.get("/literature/repository/report")
def read_literature_repository_report() -> dict[str, Any]:
    return {"ok": True, "report": literature_repository_report()}


@router.post("/literature/context/build")
def build_literature_context() -> dict[str, Any]:
    result = build_combined_context_files()
    return {
        "ok": True,
        "output_dir": str(result.output_dir),
        "domain_context_file": str(result.domain_context_file),
        "review_context_file": str(result.review_context_file),
        "methodology_context_file": str(result.methodology_context_file),
        "excluded_report_file": str(result.excluded_report_file),
        "domain_count": result.domain_count,
        "review_count": result.review_count,
        "methodology_count": result.methodology_count,
        "excluded_count": result.excluded_count,
    }


@router.post("/literature/repository/regenerate-clean")
def regenerate_literature_clean_markdown(payload: LiteratureActionPayload) -> dict[str, Any]:
    try:
        paper = regenerate_clean_markdown(Path(payload.markdown_file))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "paper": {"title": paper.get("title"), "literature_review": _literature_review_status(paper)}}


@router.post("/literature/repository/regenerate-context")
def regenerate_literature_context_markdown(payload: LiteratureActionPayload) -> dict[str, Any]:
    try:
        paper = regenerate_llm_context(Path(payload.markdown_file))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "paper": {"title": paper.get("title"), "literature_review": _literature_review_status(paper)}}


@router.post("/literature/repository/retry-extraction")
def retry_literature_repository_extraction(payload: LiteratureActionPayload) -> dict[str, Any]:
    if not payload.engine:
        raise HTTPException(status_code=400, detail="Extraction engine is required.")
    try:
        paper = retry_literature_extraction(Path(payload.markdown_file), engine=payload.engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "paper": {"title": paper.get("title"), "literature_review": _literature_review_status(paper)}}


@router.post("/zotero/sync")
def sync_zotero(
    payload: ZoteroSyncPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
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
    publisher = publisher_config(session)
    extraction_mode = publisher.extraction_mode
    api_config = ElsevierApiConfig(api_key=publisher.api_key, inst_token=publisher.inst_token, base_url=publisher.base_url, enabled=publisher.enabled)
    xml_imported = 0
    failures: list[dict[str, Any]] = []
    try:
        _, canonical_paths = _canonical_project_paths(session)
    except LookupError:
        canonical_paths = None
    if canonical_paths and extraction_mode != "pdf_only":
        for source in sources:
            creators = [" ".join(part for part in (creator.get("given"), creator.get("family")) if part).strip() for creator in source.creators]
            try:
                entry, duplicate = import_identified_item(
                    canonical_paths,
                    LiteratureIdentification(
                        zotero_key=source.provider_item_key,
                        doi=source.doi,
                        sciencedirect_url=source.url,
                        title=source.title,
                        authors=[creator for creator in creators if creator],
                        year=source.year,
                        pdf_path=None,
                        metadata_source="zotero",
                        identifier_metadata=source.identifier_metadata,
                    ),
                    publisher=api_config,
                    extraction_mode="publisher_api_required",
                )
                xml_imported += int(not duplicate and entry.get("xml_retrieved", False))
            except LiteratureExtractionError as exc:
                failures.append({"zotero_key": source.provider_item_key, "title": source.title, "message": str(exc), "diagnostics": exc.diagnostics})

    if extraction_mode == "publisher_api_required":
        if canonical_paths is None:
            failures.append({"message": "Create or select an active project before importing Zotero literature."})
        report = {"extraction_mode": extraction_mode, "last_import_status": "failed" if failures else "success", "items_imported_through_xml": xml_imported, "api_failures": len(failures), "pdf_fallbacks": 0, "pdf_used": False, "fallback_used": False, "extraction_errors": [failure["message"] for failure in failures]}
        _save_import_diagnostics(session, report)
        if failures:
            raise HTTPException(status_code=400, detail={"message": failures[0]["message"], "diagnostics": report, "failures": failures})
        return {"fetched": len(items), "inserted": result.inserted, "updated": result.updated, "skipped": result.skipped, "xml_imported": xml_imported, "pdf_used": False, "fallback_used": False, "extraction_mode": extraction_mode}

    pdf_fallbacks = 0
    if canonical_paths is not None:
        pipeline_config = literature_pipeline_config(session)
        try:
            pipeline_result = run_literature_pipeline(pipeline_config)
            pdf_fallbacks = pipeline_result.converted_markdown_count
        except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
            failures.append({"message": str(exc)})
    report = {"extraction_mode": extraction_mode, "last_import_status": "partial_failure" if failures else "success", "items_imported_through_xml": xml_imported, "api_failures": len(failures), "pdf_fallbacks": pdf_fallbacks, "pdf_used": pdf_fallbacks > 0, "fallback_used": extraction_mode == "pdf_fallback_allowed" and pdf_fallbacks > 0, "extraction_errors": [failure["message"] for failure in failures]}
    _save_import_diagnostics(session, report)
    return {
        "fetched": len(items),
        "inserted": result.inserted,
        "updated": result.updated,
        "skipped": result.skipped,
        "xml_imported": xml_imported,
        "pdf_used": pdf_fallbacks > 0,
        "fallback_used": extraction_mode == "pdf_fallback_allowed" and pdf_fallbacks > 0,
        "extraction_mode": extraction_mode,
        "failures": failures,
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
    refresh_literature_markdown_repository(session)
    return {"inserted": result.inserted, "updated": result.updated, "skipped": result.skipped}


def _global_ontology_status(session: Session) -> dict[str, Any]:
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


def _empty_ontology_scan(message: str, path: Path | None = None) -> dict[str, Any]:
    return {
        "path": str(path) if path else None,
        "exists": bool(path and path.exists()),
        "readable": bool(path and path.exists() and path.is_dir()),
        "files": [],
        "message": message,
    }


def _active_project_ontology_status(session: Session) -> dict[str, Any]:
    try:
        project = get_project(session)
    except LookupError:
        return {
            "project_required": True,
            "status": "no_project",
            "message": "Select or create a project before working with ontology files.",
            "project": None,
            "path": None,
            "selected_file": None,
            "selected_source": None,
            "scan": _empty_ontology_scan("Select or create a project before working with ontology files."),
            "term_count": 0,
            "indexed": False,
            "error": None,
        }

    project_info = project_payload(project, session)
    selected, selected_source = resolve_project_ontology_file(project)
    scan_folder = None
    if selected:
        scan_folder = selected.parent
    elif project.odk_repo_path:
        scan_folder = Path(project.odk_repo_path)
    elif project.local_path:
        scan_folder = Path(project.local_path) / "ontology"

    if scan_folder and scan_folder.exists() and scan_folder.is_dir():
        scan = scan_ontology_folder(scan_folder)
    else:
        scan = _empty_ontology_scan(
            "No ontology file configured for this project.",
            scan_folder,
        )

    term_count = 0
    error = None
    status = "ready" if selected else "missing_ontology_file"
    message = (
        f"Using {selected_source} from active project {project.name}."
        if selected
        else "No ontology file configured for this project."
    )
    if selected:
        try:
            term_count = len(index_ontology_file(selected))
        except Exception as exc:
            error = str(exc)
            status = "parse_error"
            message = f"Selected project ontology could not be parsed: {exc}"

    return {
        "project_required": True,
        "status": status,
        "message": message,
        "project": project_info,
        "path": str(scan_folder) if scan_folder else None,
        "selected_file": str(selected) if selected else None,
        "selected_source": selected_source,
        "editable_ontology_path": project.editable_ontology_path,
        "built_ontology_path": project.built_ontology_path,
        "odk_repo_path": project.odk_repo_path,
        "ontology_id": project.ontology_id,
        "base_iri": project.base_iri,
        "path_statuses": project_info.get("path_statuses", {}),
        "scan": scan,
        "term_count": term_count,
        "indexed": term_count > 0,
        "error": error,
    }


@router.get("/ontology/status")
def ontology_status(
    global_fallback: bool = False,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if global_fallback:
        return _global_ontology_status(session)
    return _active_project_ontology_status(session)


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
    return _global_ontology_status(session)


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
    project_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    try:
        terms = _indexed_terms(session, project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not load ontology terms: {exc}") from exc
    selected = search_terms(terms, q, limit=limit) if q else terms[:limit]
    return [term.to_dict() for term in selected]


@router.get("/ontology/search")
def ontology_search(
    q: str,
    limit: int = 50,
    project_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    try:
        terms = _indexed_terms(session, project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not search ontology terms: {exc}") from exc
    return [term.to_dict() for term in search_terms(terms, q, limit=limit)]


@router.get("/ontology/terms/{term_id}")
def ontology_term(
    term_id: str,
    project_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        terms = _indexed_terms(session, project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not search ontology terms: {exc}") from exc
    for term in terms:
        if term.term_id == term_id or term.iri == term_id:
            return term.to_dict()
    raise HTTPException(status_code=404, detail="Ontology term not found")


@router.get("/ontology/graph")
def ontology_graph(
    project_id: str | None = None,
    limit: int = 80,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        project = None
        try:
            project = get_project(session, project_id)
        except LookupError:
            pass

        if project:
            try:
                ontology_file, source_type = resolve_project_ontology_file(project)
            except Exception:
                ontology_file, source_type = None, None

            if not ontology_file:
                return {
                    "project_id": project.slug,
                    "ontology_source": None,
                    "ontology_source_type": None,
                    "loaded": False,
                    "class_count": 0,
                    "hierarchy_edge_count": 0,
                    "semantic_edge_count": 0,
                    "nodes": [],
                    "hierarchy_edges": [],
                    "semantic_edges": [],
                    "warnings": ["No project ontology file found. Configure or build the project ontology first."]
                }
            
            terms = index_ontology_file(ontology_file)
            tree = ontology_tree_payload(terms, root_id=None, depth_limit=2)
            nodes = tree.get("nodes", [])
            hierarchy_edges = tree.get("hierarchy_edges", [])
            semantic_edges = tree.get("relation_edges", [])
            return {
                "project_id": project.slug,
                "ontology_source": str(ontology_file),
                "ontology_source_type": source_type,
                "loaded": True,
                "class_count": len(nodes),
                "hierarchy_edge_count": len(hierarchy_edges),
                "semantic_edge_count": len(semantic_edges),
                "nodes": nodes,
                "hierarchy_edges": hierarchy_edges,
                "semantic_edges": semantic_edges,
                "edges": [{**e, "label": "subClassOf" if e.get("relation") == "is_a" else e.get("relation")} for e in hierarchy_edges],
                "warnings": tree.get("metadata", {}).get("warnings", [])
            }
        else:
            terms = _indexed_terms(session)
            graph = _graph_from_terms(terms, limit=limit)
            return {
                "project_id": None,
                "ontology_source": str(_selected_ontology_file(session) or _configured_ontology_path(session)),
                "ontology_source_type": "global",
                "loaded": True,
                "class_count": len(graph.get("nodes", [])),
                "hierarchy_edge_count": len(graph.get("edges", [])),
                "semantic_edge_count": 0,
                "nodes": graph.get("nodes", []),
                "hierarchy_edges": graph.get("edges", []),
                "semantic_edges": [],
                "edges": graph.get("edges", []),
                "warnings": []
            }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not build ontology graph: {exc}") from exc


@router.get("/ontology/tree")
def ontology_tree(
    root_id: str | None = None,
    depth_limit: int = 4,
    max_children: int = 80,
    q: str | None = None,
    project_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return ontology_tree_payload(
            _indexed_terms(session, project_id),
            root_id=root_id,
            depth_limit=max(1, min(depth_limit, 12)),
            max_children=max(10, min(max_children, 500)),
            query=q,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not build ontology tree: {exc}") from exc


@router.get("/ontology/relation-types")
def ontology_relation_types() -> dict[str, list[dict[str, Any]]]:
    return relation_type_payload()


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
    repository_skipped_files: list[dict[str, str]] = []
    if payload.document_id is not None:
        document = session.get(LiteratureDocument, payload.document_id)
    elif payload.source_id is not None:
        source = session.get(LiteratureSource, payload.source_id)
        if source is None or source.provider != "zotero":
            raise HTTPException(status_code=404, detail="Zotero entry not found")
        document = _document_from_source(session, source)
    else:
        try:
            _, project_paths = _canonical_project_paths(session)
            build_canonical_combined(project_paths)
            curated_entries = list_curated_entries(project_paths)
            text = project_paths.combined.read_text(encoding="utf-8", errors="replace") if project_paths.combined.exists() else ""
            repository_result = LiteratureRepositoryLoadResult(
                papers=[
                    {
                        "id": entry.get("canonical_id"),
                        "paper_id": entry.get("canonical_id"),
                        "title": entry.get("title"),
                        "source_file": entry.get("markdown_file"),
                        "state": "ready_for_llm",
                        "document_role": entry.get("document_role") or "domain_article",
                        "metadata_match_status": "matched",
                        "extraction_quality": "usable",
                    }
                    for entry in curated_entries
                    if entry.get("markdown_file")
                ],
                loaded_files=[Path(entry["markdown_file"]) for entry in curated_entries if entry.get("markdown_file")],
                skipped_files=[],
            )
        except LookupError:
            text, repository_result = literature_context_for_entry_generation()
        if payload.dry_run:
            return {
                "dry_run": True,
                "would_extract": bool(repository_result.papers),
                "estimated_context_size": len(text),
                "included_documents": [
                    {
                        "id": paper.get("id") or paper.get("paper_id"),
                        "title": paper.get("title"),
                        "source_file": paper.get("source_file"),
                        "state": paper.get("state"),
                        "document_role": paper.get("document_role"),
                        "metadata_match_status": paper.get("metadata_match_status"),
                        "extraction_quality": paper.get("extraction_quality"),
                    }
                    for paper in repository_result.papers
                ],
                "excluded_documents": repository_result.skipped_files,
                "message": (
                    "Valid literature is available for automatic extraction."
                    if repository_result.papers
                    else "No valid literature is available for automatic extraction."
                ),
            }
        if not repository_result.papers:
            detail = "No valid literature Markdown files are available. Import literature first."
            if repository_result.skipped_files:
                detail = (
                    "No valid literature Markdown files are available. Import literature first "
                    "or repair malformed repository Markdown files."
                )
            raise HTTPException(status_code=400, detail=detail)
        repository_skipped_files = repository_result.skipped_files
        document = _get_or_create_repository_document(session, text)

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
        "literature_warnings": repository_skipped_files,
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
    }


@router.post("/curation/suggestions/run")
def run_curation_suggestions(session: Session = Depends(get_session)) -> dict[str, Any]:
    lit_config = literature_config(session)
    literature_path = lit_config.combined_output_file
    try:
        _, project_paths = _canonical_project_paths(session)
        build_canonical_combined(project_paths)
        literature_path = project_paths.combined
    except LookupError:
        pass
    try:
        result = run_curation_suggestion_workflow(
            prompt=_curation_prompt(session),
            ontology_path=_selected_ontology_file(session),
            literature_path=literature_path,
            config=llm_config(session),
        )
    except (CurationInputError, CurationResponseError, LlmUnavailableError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ontology curation LLM request failed: {exc}") from exc

    return {
        "ok": result.ok,
        "message": result.message,
        "output_dir": str(result.output_dir),
        "request_path": str(result.request_path),
        "response_path": str(result.response_path) if result.response_path else None,
        "raw_response_path": str(result.raw_response_path) if result.raw_response_path else None,
        "suggestion_count": result.suggestion_count,
        "warning_count": result.warning_count,
        "chunk_count": result.chunk_count,
        "oversized": result.oversized,
        "input_chars": result.input_chars,
        "input_approx_tokens": result.input_approx_tokens,
        "suggestions": result.payload.get("suggestions", []),
        "warnings": result.payload.get("warnings", []),
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
    write_audit_event(
        "candidate_proposed",
        entity_type="candidate",
        entity_id=candidate.candidate_id,
        details={
            "document_id": candidate.document_id,
            "label": candidate.label,
            "review_status": candidate.review_status,
            "source": "manual",
        },
    )
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
    if "graph_review" in updates and updates["graph_review"] is not None:
        candidate.graph_review_json = json.dumps(updates["graph_review"])

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Candidate label conflicts in this document") from exc
    write_audit_event(
        "candidate_modified",
        entity_type="candidate",
        entity_id=candidate.candidate_id,
        details={"updates": sorted(updates), "review_status": candidate.review_status},
    )
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
    write_audit_event(
        "candidate_reviewed",
        entity_type="candidate",
        entity_id=candidate.candidate_id,
        details={"review_status": candidate.review_status, "rationale": payload.rationale},
    )
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
    write_audit_event(
        "candidate_decision_set",
        entity_type="candidate",
        entity_id=candidate.candidate_id,
        details={"curator_decision": candidate.curator_decision, "review_status": candidate.review_status},
    )
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
    write_audit_event(
        "candidate_rejected",
        entity_type="candidate",
        entity_id=candidate.candidate_id,
        details={"review_status": candidate.review_status, "reason": payload.reason},
    )
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


@router.post("/odk/workflow")
def run_odk_workflow(
    payload: OdkWorkflowPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not payload.dry_run and not payload.production:
        raise HTTPException(
            status_code=400,
            detail="Pass production=true with dry_run=false to allow implementation, validation, and upload.",
        )
    config = config_from_settings(
        dry_run=payload.dry_run,
        suggestion_file=Path(payload.suggestion_file) if payload.suggestion_file else None,
    )
    result = run_approved_candidate_workflow(session, config=config)
    response = {
        "ok": result.ok,
        "message": result.message,
        "dry_run": result.dry_run,
        "accepted_candidate_ids": result.accepted_candidate_ids,
        "skipped_candidate_ids": result.skipped_candidate_ids,
        "implemented_path": result.implemented_path,
        "audit_log_path": result.audit_log_path,
        "suggestion_file": result.suggestion_file,
        "validation": (
            {
                "returncode": result.validation.returncode,
                "stdout": result.validation.stdout,
                "stderr": result.validation.stderr,
            }
            if result.validation
            else None
        ),
        "upload": (
            {
                "ok": result.upload.ok,
                "message": result.upload.message,
                "commit_url": result.upload.commit_url,
            }
            if result.upload
            else None
        ),
    }
    if not result.ok:
        raise HTTPException(status_code=400, detail=response)
    return response


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
