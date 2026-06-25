from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.models.db import (
    CurationRun,
    EvaluationMetric,
    LiteratureSource,
    OdkOperationLog,
    Project,
    ReviewDecision,
    Suggestion,
)


PROMPT_STRATEGIES = {
    "literature_only": "Suggest ontology terms and relations grounded only in the combined literature.",
    "ontology_only": "Identify missing definitions, relation inconsistencies, and structural gaps in the ontology.",
    "literature_plus_ontology": "Suggest literature-grounded ontology changes checked against the current ontology.",
    "structured_relation_extraction": "Extract subject-relation-object candidates with evidence spans.",
}

PROJECT_TYPES = {
    "upper_bioprocess_ontology",
    "domain_ontology",
    "module",
    "application_ontology",
    "existing_ontology_project",
    "imported_reference_ontology",
}

BPO_SCOPE_SECTIONS = [
    "bioprocess",
    "upstream process",
    "downstream process",
    "unit operation",
    "biological material",
    "chemical material",
    "process input",
    "process output",
    "process parameter",
    "process condition",
    "device or equipment",
    "analytical method",
    "measurement process",
    "measurement datum",
    "data object",
    "process model",
    "quality attribute",
    "control strategy",
    "sample",
    "experiment or run",
]

REVIEW_STATUSES = {
    "accepted",
    "edited",
    "rejected",
    "duplicate",
    "unsupported",
    "further_review",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def term_prefix_from_pattern_or_id(term_id_pattern: str | None, ontology_id: str) -> str:
    if term_id_pattern:
        return term_id_pattern.split("_", 1)[0].upper()
    return ontology_id.upper()


def project_layout(project_path: Path) -> dict[str, Path]:
    return {
        "root": project_path,
        "literature": project_path / "literature",
        "literature_sources": project_path / "literature" / "sources",
        "literature_pdf": project_path / "literature" / "pdf",
        "literature_markdown": project_path / "literature" / "markdown",
        "literature_metadata": project_path / "literature" / "metadata",
        "literature_curated": project_path / "literature" / "curated",
        "literature_curated_markdown": project_path / "literature" / "curated" / "markdown",
        "literature_curated_metadata": project_path / "literature" / "curated" / "metadata",
        "literature_diagnostics": project_path / "literature" / "diagnostics",
        "ontology": project_path / "ontology",
        "ontology_odk": project_path / "ontology" / "odk",
        "ontology_templates": project_path / "ontology" / "templates",
        "ontology_builds": project_path / "ontology" / "builds",
        "ontology_releases": project_path / "ontology" / "releases",
        "curation": project_path / "curation",
        "curation_runs": project_path / "curation" / "runs",
        "curation_prompts": project_path / "curation" / "prompts",
        "curation_suggestions": project_path / "curation" / "suggestions",
        "curation_reviews": project_path / "curation" / "reviews",
        "curation_exports": project_path / "curation" / "exports",
        "evaluation": project_path / "evaluation",
        "evaluation_metrics": project_path / "evaluation" / "metrics",
        "evaluation_reports": project_path / "evaluation" / "reports",
        "logs": project_path / "logs",
    }


def create_project_folders(project_path: Path) -> None:
    for path in project_layout(project_path).values():
        path.mkdir(parents=True, exist_ok=True)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _clean_list(values: list[str] | None) -> list[str]:
    return [str(item).strip() for item in values or [] if str(item).strip()]


def _looks_like_iri(value: str | None) -> bool:
    if not value:
        return True
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", value.strip(), flags=re.IGNORECASE))


def suggest_base_iri(ontology_id: str | None) -> str | None:
    normalized = re.sub(r"[^a-z0-9_]+", "", (ontology_id or "").strip().lower())
    if not normalized:
        return None
    return f"http://purl.obolibrary.org/obo/{normalized}.owl"


def path_status(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {
            "path": None,
            "configured": False,
            "exists": False,
            "status": "not_configured",
            "message": "Optional path not configured.",
        }
    path = Path(path_value)
    exists = path.exists()
    return {
        "path": path_value,
        "configured": True,
        "exists": exists,
        "status": "ready" if exists else "missing",
        "message": "Path exists." if exists else "Configured path does not exist yet.",
    }


def resolve_project_ref(session: Session, project_ref: str | int | None) -> Project | None:
    if project_ref in (None, ""):
        return None
    if isinstance(project_ref, int) or str(project_ref).isdigit():
        return session.get(Project, int(project_ref))
    value = str(project_ref)
    return session.scalar(
        select(Project).where(
            (Project.slug == value) | (Project.ontology_id == value)
        )
    )


def project_children(session: Session, project: Project) -> list[Project]:
    return session.scalars(
        select(Project).where(Project.parent_project_id == project.id).order_by(Project.name)
    ).all()


def literature_project_tag_count(session: Session, project: Project) -> int:
    tags = {project.ontology_id}
    count = 0
    for source in session.scalars(select(LiteratureSource)).all():
        project_tags = set(_json_list(source.project_tags_json))
        if tags & project_tags:
            count += 1
    return count


def _parent_chain(session: Session, project: Project) -> list[Project]:
    chain: list[Project] = []
    seen: set[int] = set()
    current = project
    while current.parent_project_id is not None and current.parent_project_id not in seen:
        seen.add(current.parent_project_id)
        parent = session.get(Project, current.parent_project_id)
        if parent is None:
            break
        chain.append(parent)
        current = parent
    return chain


def _assert_unique_ontology_id(session: Session, ontology_id: str, *, current_project_id: int | None = None) -> None:
    normalized = ontology_id.strip().casefold()
    if not normalized:
        raise ValueError("Ontology ID is required")
    projects = session.scalars(select(Project)).all()
    for project in projects:
        if current_project_id is not None and project.id == current_project_id:
            continue
        if project.ontology_id.casefold() == normalized:
            raise ValueError(f"Ontology ID already exists: {ontology_id}")


def _would_create_cycle(session: Session, project_id: int, parent_project_id: int | None) -> bool:
    current_id = parent_project_id
    seen: set[int] = set()
    while current_id is not None:
        if current_id == project_id:
            return True
        if current_id in seen:
            return True
        seen.add(current_id)
        parent = session.get(Project, current_id)
        current_id = parent.parent_project_id if parent else None
    return False


def _validate_project_fields(
    session: Session,
    *,
    name: str,
    ontology_id: str,
    project_type: str,
    base_iri: str | None,
    parent_project: Project | None,
    current_project_id: int | None = None,
) -> None:
    if not name.strip():
        raise ValueError("Project name is required")
    _assert_unique_ontology_id(session, ontology_id, current_project_id=current_project_id)
    if project_type not in PROJECT_TYPES:
        raise ValueError(f"Unsupported project type: {project_type}")
    if not _looks_like_iri(base_iri):
        raise ValueError("Base IRI must look like an IRI, for example http://..., https://..., or urn:...")
    if current_project_id is not None and parent_project is not None:
        if parent_project.id == current_project_id:
            raise ValueError("Project cannot be its own parent")
        if _would_create_cycle(session, current_project_id, parent_project.id):
            raise ValueError("Project parent would create a circular hierarchy")


def write_project_json(project: Project) -> None:
    path = Path(project.local_path)
    create_project_folders(path)
    payload = project_payload(project)
    (path / "project.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    source_config = path / "literature" / "source_config.json"
    if not source_config.exists():
        source_config.write_text(json.dumps({"source_path": None, "source_type": "zotero_storage"}, indent=2), encoding="utf-8")


def create_project(
    session: Session,
    *,
    name: str,
    ontology_id: str,
    ontology_title: str | None,
    base_iri: str | None,
    local_workspace_path: Path,
    github_url: str | None = None,
    zotero_literature_source_path: str | None = None,
    odk_repo_path: str | None = None,
    term_id_pattern: str | None = None,
    description: str | None = None,
    project_type: str = "domain_ontology",
    parent_project_ref: str | int | None = None,
    ontology_scope: list[str] | None = None,
    minimal_scope_notes: str | None = None,
    ontology_namespace: str | None = None,
    editable_ontology_path: str | None = None,
    built_ontology_path: str | None = None,
    literature_repository_path: str | None = None,
    local_git_repository_path: str | None = None,
    activate: bool = True,
) -> Project:
    parent_project = resolve_project_ref(session, parent_project_ref)
    if parent_project_ref not in (None, "") and parent_project is None:
        raise ValueError(f"Parent project not found: {parent_project_ref}")
    _validate_project_fields(
        session,
        name=name,
        ontology_id=ontology_id,
        project_type=project_type,
        base_iri=base_iri,
        parent_project=parent_project,
    )
    slug_base = slugify(name)
    slug = slug_base
    counter = 2
    while session.scalar(select(Project).where(Project.slug == slug)) is not None:
        slug = f"{slug_base}-{counter}"
        counter += 1

    project_path = local_workspace_path / "projects" / slug
    create_project_folders(project_path)
    if activate:
        session.execute(update(Project).values(active=False))
    project = Project(
        name=name,
        slug=slug,
        description=description,
        ontology_id=ontology_id,
        ontology_title=ontology_title,
        project_type=project_type,
        parent_project_id=parent_project.id if parent_project else None,
        ontology_scope=json.dumps(_clean_list(ontology_scope)),
        minimal_scope_notes=minimal_scope_notes,
        ontology_namespace=ontology_namespace or ontology_id.lower(),
        base_iri=base_iri,
        term_id_prefix=term_prefix_from_pattern_or_id(term_id_pattern, ontology_id),
        local_path=str(project_path),
        odk_repo_path=odk_repo_path or str(project_path / "ontology" / "odk"),
        editable_ontology_path=editable_ontology_path,
        built_ontology_path=built_ontology_path,
        literature_repository_path=literature_repository_path or str(project_path / "literature"),
        local_git_repository_path=local_git_repository_path,
        github_url=github_url,
        active=activate,
    )
    session.add(project)
    session.flush()
    write_project_json(project)
    if zotero_literature_source_path:
        source_config = project_path / "literature" / "source_config.json"
        source_config.write_text(
            json.dumps(
                {"source_path": zotero_literature_source_path, "source_type": "zotero_storage"},
                indent=2,
            ),
            encoding="utf-8",
        )
    session.commit()
    session.refresh(project)
    return project


def _project_summary(project: Project | None) -> dict[str, Any] | None:
    if project is None:
        return None
    return {
        "id": project.id,
        "project_id": project.slug,
        "slug": project.slug,
        "name": project.name,
        "ontology_id": project.ontology_id,
        "project_type": project.project_type,
    }


def project_payload(project: Project, session: Session | None = None) -> dict[str, Any]:
    path = Path(project.local_path)
    layout = project_layout(path)
    parent = session.get(Project, project.parent_project_id) if session and project.parent_project_id else None
    children = project_children(session, project) if session else []
    parent_chain = list(reversed(_parent_chain(session, project))) if session else []
    return {
        "id": project.id,
        "project_id": project.slug,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "ontology_id": project.ontology_id,
        "canonical_project_tag": project.ontology_id,
        "project_tag": project.ontology_id,
        "ontology_title": project.ontology_title,
        "project_type": project.project_type,
        "parent_project_id": project.parent_project_id,
        "parent_project": _project_summary(parent),
        "parent_chain": [_project_summary(item) for item in parent_chain],
        "children": [_project_summary(item) for item in children],
        "child_count": len(children),
        "ontology_scope": _json_list(project.ontology_scope),
        "minimal_scope_notes": project.minimal_scope_notes,
        "ontology_namespace": project.ontology_namespace,
        "base_iri": project.base_iri,
        "suggested_base_iri": suggest_base_iri(project.ontology_id),
        "term_id_prefix": project.term_id_prefix,
        "local_path": project.local_path,
        "odk_repo_path": project.odk_repo_path,
        "editable_ontology_path": project.editable_ontology_path,
        "built_ontology_path": project.built_ontology_path,
        "literature_repository_path": project.literature_repository_path,
        "local_git_repository_path": project.local_git_repository_path,
        "path_statuses": {
            "workspace_path": path_status(project.local_path),
            "odk_repo_path": path_status(project.odk_repo_path),
            "editable_ontology_path": path_status(project.editable_ontology_path),
            "built_ontology_path": path_status(project.built_ontology_path),
            "literature_repository_path": path_status(project.literature_repository_path),
            "local_git_repository_path": path_status(project.local_git_repository_path),
        },
        "github_url": project.github_url,
        "literature_project_tag_count": literature_project_tag_count(session, project) if session else 0,
        "active": project.active,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "paths": {key: str(value) for key, value in layout.items()},
    }


def update_project_metadata(session: Session, project: Project, updates: dict[str, Any]) -> Project:
    parent_was_provided = "parent_project_id" in updates or "parent_project_ref" in updates
    parent_ref = updates.pop("parent_project_id", None)
    if "parent_project_ref" in updates:
        parent_ref = updates.pop("parent_project_ref")
    parent_project = resolve_project_ref(session, parent_ref) if parent_ref not in (None, "") else None
    if parent_ref not in (None, "") and parent_project is None:
        raise ValueError(f"Parent project not found: {parent_ref}")

    new_name = updates.get("name", project.name)
    new_ontology_id = updates.get("ontology_id", project.ontology_id)
    new_project_type = updates.get("project_type", project.project_type)
    new_base_iri = updates.get("base_iri", project.base_iri)
    _validate_project_fields(
        session,
        name=new_name,
        ontology_id=new_ontology_id,
        project_type=new_project_type,
        base_iri=new_base_iri,
        parent_project=parent_project,
        current_project_id=project.id,
    )
    if parent_was_provided:
        project.parent_project_id = parent_project.id if parent_project else None

    list_fields = {
        "ontology_scope": "ontology_scope",
    }
    for public_name, model_name in list_fields.items():
        if public_name in updates:
            setattr(project, model_name, json.dumps(_clean_list(updates.pop(public_name))))
    for field, value in updates.items():
        setattr(project, field, value)
    if "ontology_id" in updates and "ontology_namespace" not in updates:
        project.ontology_namespace = project.ontology_id.lower()
    project.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(project)
    write_project_json(project)
    return project


def get_project(session: Session, project_ref: str | int | None = None) -> Project:
    if project_ref is None:
        project = session.scalar(select(Project).where(Project.active.is_(True)).order_by(Project.id))
        if project is None:
            raise LookupError("No active project selected")
        return project
    if isinstance(project_ref, int) or str(project_ref).isdigit():
        project = session.get(Project, int(project_ref))
    else:
        project = session.scalar(select(Project).where(Project.slug == str(project_ref)))
    if project is None:
        raise LookupError(f"Project not found: {project_ref}")
    return project


def select_project(session: Session, project_ref: str | int) -> Project:
    project = get_project(session, project_ref)
    session.execute(update(Project).values(active=False))
    project.active = True
    project.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(project)
    return project


def default_prompt(strategy: str) -> str:
    detail = PROMPT_STRATEGIES.get(strategy)
    if detail is None:
        raise ValueError(f"Unsupported prompt strategy: {strategy}")
    return (
        f"Strategy: {strategy}\n"
        f"{detail}\n\n"
        "Return JSON with a top-level suggestions array. Each suggestion should include "
        "suggestion_type, label, definition, parent_class, relations, synonyms, evidence, "
        "duplicate_check, and confidence."
    )


def create_curation_run(
    session: Session,
    project: Project,
    *,
    name: str | None,
    strategy: str,
    model: str | None,
    prompt_text: str | None,
    context_configuration: dict[str, Any] | None = None,
    raw_output: str | None = None,
) -> CurationRun:
    if strategy not in PROMPT_STRATEGIES:
        raise ValueError(f"Unsupported prompt strategy: {strategy}")
    project_path = Path(project.local_path)
    layout = project_layout(project_path)
    run = CurationRun(
        project_id=project.id,
        name=name or f"{strategy} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        model=model,
        prompt_strategy=strategy,
        context_configuration_json=json.dumps(context_configuration or {}, sort_keys=True),
        prompt_text=prompt_text or default_prompt(strategy),
        literature_snapshot_path=str(layout["literature"] / "combined_literature.md"),
        ontology_snapshot_path=project.odk_repo_path,
        raw_output=raw_output,
        status="created",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _json_array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_suggestions(raw_output: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return [], f"Malformed JSON stored as raw output: {exc}"
    suggestions = payload.get("suggestions") if isinstance(payload, dict) else payload
    if not isinstance(suggestions, list):
        return [], "JSON did not contain a suggestions array"
    return [item for item in suggestions if isinstance(item, dict)], None


def persist_suggestions(session: Session, run: CurationRun, raw_output: str) -> tuple[int, str | None]:
    suggestions, warning = parse_suggestions(raw_output)
    for item in suggestions:
        evidence = _json_array(item.get("evidence"))
        first_evidence = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
        relations = _json_array(item.get("relations"))
        first_relation = relations[0] if relations and isinstance(relations[0], dict) else {}
        suggestion = Suggestion(
            project_id=run.project_id,
            curation_run_id=run.id,
            suggestion_type=str(item.get("suggestion_type") or "class"),
            label=str(item.get("label") or "Untitled suggestion"),
            definition=item.get("definition"),
            parent_class=item.get("parent_class"),
            relation=first_relation.get("relation") or item.get("relation"),
            target=first_relation.get("target") or item.get("target"),
            evidence_text=first_evidence.get("quote_or_span") or item.get("evidence_text"),
            evidence_source=first_evidence.get("source") or first_evidence.get("document_title"),
            evidence_json=json.dumps(evidence),
            relations_json=json.dumps(relations),
            synonyms_json=json.dumps(_json_array(item.get("synonyms"))),
            duplicate_check_json=json.dumps(item.get("duplicate_check") or {}),
            confidence=str(item.get("confidence") or ""),
            raw_llm_output=json.dumps(item, sort_keys=True),
        )
        session.add(suggestion)
    run.raw_output = raw_output
    run.status = "parsed_with_warnings" if warning else "parsed"
    session.commit()
    return len(suggestions), warning


def suggestion_payload(suggestion: Suggestion, latest_review: ReviewDecision | None = None) -> dict[str, Any]:
    return {
        "id": suggestion.id,
        "project_id": suggestion.project_id,
        "curation_run_id": suggestion.curation_run_id,
        "suggestion_type": suggestion.suggestion_type,
        "label": suggestion.label,
        "definition": suggestion.definition,
        "parent_class": suggestion.parent_class,
        "relation": suggestion.relation,
        "target": suggestion.target,
        "evidence_text": suggestion.evidence_text,
        "evidence_source": suggestion.evidence_source,
        "evidence": json.loads(suggestion.evidence_json or "[]"),
        "relations": json.loads(suggestion.relations_json or "[]"),
        "synonyms": json.loads(suggestion.synonyms_json or "[]"),
        "duplicate_check": json.loads(suggestion.duplicate_check_json or "{}"),
        "confidence": suggestion.confidence,
        "raw_llm_output": suggestion.raw_llm_output,
        "review_status": latest_review.status if latest_review else "unreviewed",
        "latest_review": review_payload(latest_review) if latest_review else None,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
    }


def review_payload(review: ReviewDecision | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "id": review.id,
        "suggestion_id": review.suggestion_id,
        "reviewer": review.reviewer,
        "status": review.status,
        "edited_label": review.edited_label,
        "edited_definition": review.edited_definition,
        "edited_parent_class": review.edited_parent_class,
        "edited_relation": review.edited_relation,
        "edited_target": review.edited_target,
        "relation_correct": review.relation_correct,
        "comment": review.comment,
        "review_time_seconds": review.review_time_seconds,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


def latest_reviews_by_suggestion(session: Session, suggestion_ids: list[int]) -> dict[int, ReviewDecision]:
    if not suggestion_ids:
        return {}
    reviews = session.scalars(
        select(ReviewDecision)
        .where(ReviewDecision.suggestion_id.in_(suggestion_ids))
        .order_by(ReviewDecision.suggestion_id, ReviewDecision.created_at.desc(), ReviewDecision.id.desc())
    ).all()
    result: dict[int, ReviewDecision] = {}
    for review in reviews:
        result.setdefault(review.suggestion_id, review)
    return result


def add_review(
    session: Session,
    suggestion: Suggestion,
    *,
    status: str,
    reviewer: str | None = None,
    edited_label: str | None = None,
    edited_definition: str | None = None,
    edited_parent_class: str | None = None,
    edited_relation: str | None = None,
    edited_target: str | None = None,
    relation_correct: bool | None = None,
    comment: str | None = None,
    review_time_seconds: int | None = None,
) -> ReviewDecision:
    if status not in REVIEW_STATUSES:
        raise ValueError(f"Unsupported review status: {status}")
    review = ReviewDecision(
        suggestion_id=suggestion.id,
        reviewer=reviewer,
        status=status,
        edited_label=edited_label,
        edited_definition=edited_definition,
        edited_parent_class=edited_parent_class,
        edited_relation=edited_relation,
        edited_target=edited_target,
        relation_correct=relation_correct,
        comment=comment,
        review_time_seconds=review_time_seconds,
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def compute_evaluation(session: Session, project: Project, run_id: int | None = None) -> dict[str, Any]:
    statement = select(Suggestion).where(Suggestion.project_id == project.id)
    if run_id is not None:
        statement = statement.where(Suggestion.curation_run_id == run_id)
    suggestions = session.scalars(statement).all()
    latest_reviews = latest_reviews_by_suggestion(session, [item.id for item in suggestions])
    reviewed = [review for review in latest_reviews.values()]
    total_reviewed = len(reviewed)
    status_counts = {status: 0 for status in REVIEW_STATUSES}
    for review in reviewed:
        status_counts[review.status] = status_counts.get(review.status, 0) + 1
    accepted_or_edited = status_counts.get("accepted", 0) + status_counts.get("edited", 0)
    relation_reviews = [review for review in reviewed if review.relation_correct is not None]
    evidence_count = sum(1 for item in suggestions if item.evidence_text or json.loads(item.evidence_json or "[]"))
    total_review_time = sum(review.review_time_seconds or 0 for review in reviewed)
    metrics = {
        "total_suggestions": len(suggestions),
        "total_reviewed": total_reviewed,
        "accepted": status_counts.get("accepted", 0),
        "edited": status_counts.get("edited", 0),
        "rejected": status_counts.get("rejected", 0),
        "duplicate": status_counts.get("duplicate", 0),
        "unsupported": status_counts.get("unsupported", 0),
        "further_review": status_counts.get("further_review", 0),
        "precision_accept_only": (status_counts.get("accepted", 0) / total_reviewed) if total_reviewed else 0.0,
        "precision_accept_or_edit": (accepted_or_edited / total_reviewed) if total_reviewed else 0.0,
        "unsupported_rate": (status_counts.get("unsupported", 0) / total_reviewed) if total_reviewed else 0.0,
        "duplicate_rate": (status_counts.get("duplicate", 0) / total_reviewed) if total_reviewed else 0.0,
        "relation_correctness": (
            sum(1 for review in relation_reviews if review.relation_correct) / len(relation_reviews)
        ) if relation_reviews else 0.0,
        "evidence_traceability": (evidence_count / len(suggestions)) if suggestions else 0.0,
        "total_review_time_seconds": total_review_time,
        "average_review_time_seconds": (total_review_time / total_reviewed) if total_reviewed else 0.0,
    }
    for name, value in metrics.items():
        if isinstance(value, int | float):
            session.add(
                EvaluationMetric(
                    project_id=project.id,
                    curation_run_id=run_id,
                    metric_name=name,
                    metric_value=float(value),
                    details_json=json.dumps({"computed_at": datetime.now(timezone.utc).isoformat()}),
                )
            )
    session.commit()
    return {"project": project_payload(project), "run_id": run_id, "metrics": metrics}


def normalized_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.casefold()).strip()


def compare_runs(session: Session, project: Project, first_run_id: int, second_run_id: int) -> dict[str, Any]:
    first = session.scalars(
        select(Suggestion).where(Suggestion.project_id == project.id, Suggestion.curation_run_id == first_run_id)
    ).all()
    second = session.scalars(
        select(Suggestion).where(Suggestion.project_id == project.id, Suggestion.curation_run_id == second_run_id)
    ).all()
    first_labels = {item.label for item in first}
    second_labels = {item.label for item in second}
    first_norm = {normalized_label(item.label) for item in first}
    second_norm = {normalized_label(item.label) for item in second}
    first_triples = {
        (normalized_label(item.label), item.relation or "", normalized_label(item.target or ""))
        for item in first
        if item.relation or item.target
    }
    second_triples = {
        (normalized_label(item.label), item.relation or "", normalized_label(item.target or ""))
        for item in second
        if item.relation or item.target
    }
    return {
        "project": project_payload(project),
        "runs": [first_run_id, second_run_id],
        "exact_label_overlap": len(first_labels & second_labels),
        "normalized_label_overlap": len(first_norm & second_norm),
        "relation_triple_overlap": len(first_triples & second_triples),
        "first_count": len(first),
        "second_count": len(second),
    }


def accepted_suggestions_for_export(session: Session, project: Project, include_further_review: bool = False) -> list[Suggestion]:
    suggestions = session.scalars(select(Suggestion).where(Suggestion.project_id == project.id)).all()
    latest = latest_reviews_by_suggestion(session, [item.id for item in suggestions])
    allowed = {"accepted", "edited"}
    if include_further_review:
        allowed.add("further_review")
    return [item for item in suggestions if latest.get(item.id) and latest[item.id].status in allowed]


def export_suggestions_tsv(session: Session, project: Project, include_further_review: bool = False) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["ID", "TYPE", "LABEL", "DEFINITION", "PARENT", "RELATION", "TARGET", "EVIDENCE"])
    latest = latest_reviews_by_suggestion(session, [])
    for suggestion in accepted_suggestions_for_export(session, project, include_further_review):
        if suggestion.id not in latest:
            latest = latest_reviews_by_suggestion(session, [suggestion.id])
        review = latest.get(suggestion.id)
        writer.writerow(
            [
                f"{project.term_id_prefix or project.ontology_id.upper()}_PENDING_{suggestion.id:06d}",
                suggestion.suggestion_type,
                review.edited_label if review and review.edited_label else suggestion.label,
                review.edited_definition if review and review.edited_definition else suggestion.definition or "",
                review.edited_parent_class if review and review.edited_parent_class else suggestion.parent_class or "",
                review.edited_relation if review and review.edited_relation else suggestion.relation or "",
                review.edited_target if review and review.edited_target else suggestion.target or "",
                suggestion.evidence_text or "",
            ]
        )
    return output.getvalue()


def log_odk_operation(
    session: Session,
    project: Project,
    *,
    operation: str,
    command: str | None = None,
    working_directory: str | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    exit_code: int | None = None,
    status: str = "logged",
) -> OdkOperationLog:
    log = OdkOperationLog(
        project_id=project.id,
        operation=operation,
        command=command,
        working_directory=working_directory,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        status=status,
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


def validate_project_odk(session: Session, project: Project) -> dict[str, Any]:
    repo = Path(project.odk_repo_path or "")
    edit_file = repo / "src" / "ontology" / f"{project.ontology_id}-edit.owl"
    checks = {
        "repo_path": str(repo),
        "repo_exists": repo.exists(),
        "edit_file": str(edit_file),
        "edit_file_exists": edit_file.exists(),
        "git_exists": shutil.which("git") is not None,
        "docker_exists": shutil.which("docker") is not None,
    }
    status = "ok" if checks["repo_exists"] and checks["edit_file_exists"] else "warning"
    log_odk_operation(
        session,
        project,
        operation="validate",
        working_directory=str(repo),
        stdout=json.dumps(checks, indent=2),
        exit_code=0 if status == "ok" else 1,
        status=status,
    )
    return checks | {"status": status}


def hash_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
