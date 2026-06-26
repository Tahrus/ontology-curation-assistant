from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.extraction.service import build_candidate_id, normalize_label
from backend.app.literature.canonical import RepositoryPaths, list_curated_entries, list_entries
from backend.app.llm.clients import LlmClientError, LlmTextResult, estimate_input_size, generate_text
from backend.app.llm.presets import normalize_provider_id
from backend.app.llm.service import LlmUnavailableError
from backend.app.ontology_suggestion_diagnostics import diagnostic_payload, run_api_function_test
from backend.app.models.core import ReviewStatus
from backend.app.models.db import (
    AppSetting,
    CandidateTermRecord,
    CurationRun,
    LiteratureDocument,
    Project,
    Suggestion,
)
from backend.app.ontology.local import index_ontology_file
from backend.app.projects import add_review, get_project
from backend.app.services.runtime_config import LlmRuntimeConfig, llm_config


DATA_ROOT = Path("data") / "ontology_suggestions"
PROMPT_DIR = DATA_ROOT / "prompts"
RUN_DIR = DATA_ROOT / "runs"
LOG_DIR = DATA_ROOT / "logs"
FUNCTION_TEST_LOG_DIR = LOG_DIR / "api_function_tests"
TEMPLATE_FILE = PROMPT_DIR / "templates.json"
SYSTEM_PROMPT = "Return strict JSON only. Do not create ontology IDs or ontology files."
PROMPT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
REQUIRED_TEMPLATE_FIELDS = {
    "id",
    "title",
    "short_description",
    "use_case",
    "task_type",
    "expected_output_format",
    "input_scope",
    "cost_level",
    "version",
    "active",
    "created_at",
    "updated_at",
}

LiteratureScope = Literal["one", "selected", "all_curated", "all_uncurated"]
OntologyContextMode = Literal["labels_only", "labels_definitions", "labels_definitions_relations", "full"]
SuggestionCaller = Callable[[str, LlmRuntimeConfig], str | LlmTextResult]


INITIAL_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "conservative_term_suggestions",
        "title": "Conservative term suggestions",
        "short_description": "Suggests only high-confidence ontology class candidates from selected literature.",
        "use_case": "Suggest only high-confidence ontology class candidates from one selected paper. Avoid speculative terms.",
        "task_type": "term_suggestion",
        "expected_output_format": "json",
        "input_scope": "single_literature_item",
        "cost_level": "low",
        "prompt_text": "# Task\n\nSuggest conservative ontology class candidates from the selected literature item.\n\n# Constraints\n\nOnly suggest terms explicitly supported by the provided literature.\nDo not invent speculative terms.\nPrefer no suggestion over a weak suggestion.\n\n# Output\n\nReturn only valid JSON matching the required schema.",
    },
    {
        "id": "relation_suggestions",
        "title": "Relation suggestions",
        "short_description": "Suggests evidence-supported relations between ontology terms.",
        "use_case": "Suggest relations between existing or newly proposed ontology terms, with evidence.",
        "task_type": "relation_suggestion",
        "expected_output_format": "json",
        "input_scope": "selected_literature_items",
        "cost_level": "medium",
        "prompt_text": "# Task\n\nSuggest evidence-supported relations between ontology terms.\n\n# Constraints\n\nOnly propose relations that are directly supported by the selected literature.\nInclude the source term, relation label, target term, evidence quote, and rationale.\n\n# Output\n\nReturn only valid JSON matching the required ontology suggestion schema.",
    },
    {
        "id": "definition_improvement",
        "title": "Definition improvement",
        "short_description": "Improves existing ontology definitions using literature evidence.",
        "use_case": "Improve existing ontology definitions using project literature as evidence.",
        "task_type": "definition_improvement",
        "expected_output_format": "json",
        "input_scope": "ontology_terms_and_literature",
        "cost_level": "low",
        "prompt_text": "# Task\n\nImprove existing ontology definitions using selected literature evidence.\n\n# Constraints\n\nKeep definitions concise, genus-differentia oriented where possible, and evidence-backed.\nDo not replace a definition unless the literature clearly improves precision or clarity.\n\n# Output\n\nReturn only valid JSON matching the required schema.",
    },
    {
        "id": "duplicate_check",
        "title": "Duplicate check",
        "short_description": "Checks whether proposed ontology terms duplicate existing ontology classes.",
        "use_case": "Check whether proposed terms may duplicate existing ontology classes.",
        "task_type": "duplicate_check",
        "expected_output_format": "json",
        "input_scope": "ontology_context",
        "cost_level": "low",
        "prompt_text": "# Task\n\nCheck whether proposed ontology terms duplicate existing ontology classes.\n\n# Constraints\n\nUse existing labels, synonyms, definitions, and parent context.\nFlag likely duplicates as duplicate_warning suggestions with evidence and rationale.\n\n# Output\n\nReturn only valid JSON matching the required schema.",
    },
    {
        "id": "evidence_mapping",
        "title": "Evidence mapping",
        "short_description": "Maps proposed ontology suggestions to exact supporting evidence snippets.",
        "use_case": "Map proposed ontology suggestions to exact supporting evidence snippets.",
        "task_type": "evidence_mapping",
        "expected_output_format": "json",
        "input_scope": "literature_item",
        "cost_level": "medium",
        "prompt_text": "# Task\n\nMap ontology suggestions to exact literature evidence snippets.\n\n# Constraints\n\nPrefer short quotes that directly support the suggestion.\nKeep locations when available, such as section names, figure/table labels, or paragraph context.\n\n# Output\n\nReturn only valid JSON matching the required schema.",
    },
    {
        "id": "competency_question_extraction",
        "title": "Competency question extraction",
        "short_description": "Extracts possible competency questions from project literature.",
        "use_case": "Extract possible competency questions from project literature.",
        "task_type": "competency_question_extraction",
        "expected_output_format": "json",
        "input_scope": "project_literature",
        "cost_level": "low",
        "prompt_text": "# Task\n\nExtract possible competency questions from project literature.\n\n# Constraints\n\nQuestions should describe real domain queries the ontology should answer.\nTie each question to evidence from the provided literature.\n\n# Output\n\nReturn only valid JSON matching the required schema.",
    },
]

@dataclass(frozen=True)
class PromptTemplate:
    id: str
    title: str
    short_description: str
    use_case: str
    task_type: str
    expected_output_format: str
    input_scope: str
    cost_level: str
    prompt_text: str
    created_at: str
    updated_at: str
    version: int = 1
    active: bool = True

    @property
    def name(self) -> str:
        return self.title

    @property
    def description(self) -> str:
        return self.short_description


@dataclass(frozen=True)
class ApiFunctionTestDiagnostics:
    status: str
    stage: str
    provider: str | None
    model: str | None
    base_url: str | None
    api_key_present: bool
    api_key_preview: str
    http_status: int | None = None
    content_type: str | None = None
    response_body_length: int = 0
    raw_response_preview: str | None = None
    parsed_json: bool = False
    schema_valid: bool = False
    error_type: str | None = None
    error_message: str | None = None
    suggested_fix: str | None = None
    run_id: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class Pricing:
    input_cost_per_1m_tokens: float | None = None
    output_cost_per_1m_tokens: float | None = None
    cached_input_cost_per_1m_tokens: float | None = None
    monthly_budget: float | None = None
    estimated_spend_this_month: float = 0.0
    warning_threshold: float = 0.8


def ensure_storage() -> None:
    for path in [PROMPT_DIR, RUN_DIR, LOG_DIR, FUNCTION_TEST_LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    if TEMPLATE_FILE.exists():
        legacy = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
        for item in legacy if isinstance(legacy, list) else []:
            template = _template_from_payload(item)
            _template_path(template.id).write_text(_template_to_markdown(template), encoding="utf-8")
        TEMPLATE_FILE.rename(PROMPT_DIR / "templates.legacy.json")
    for json_path in sorted(PROMPT_DIR.glob("*.json")):
        if json_path.name.endswith(".legacy.json"):
            continue
        template = _template_from_payload(json.loads(json_path.read_text(encoding="utf-8")))
        md_path = _template_path(template.id)
        if not md_path.exists():
            md_path.write_text(_template_to_markdown(template), encoding="utf-8")
    for item in INITIAL_TEMPLATES:
        template = _template_from_payload(item)
        path = _template_path(template.id)
        if not path.exists():
            path.write_text(_template_to_markdown(template), encoding="utf-8")


def list_prompt_templates(*, include_inactive: bool = False) -> list[PromptTemplate]:
    ensure_storage()
    templates = [_template_from_markdown(path.read_text(encoding="utf-8"), path=path) for path in sorted(PROMPT_DIR.glob("*.md"))]
    return [item for item in templates if include_inactive or item.active]


def get_prompt_template(template_id: str, *, include_inactive: bool = False) -> PromptTemplate:
    for template in list_prompt_templates(include_inactive=include_inactive):
        if template.id == template_id:
            return template
    raise ValueError(f"Unknown prompt template: {template_id}")


def save_prompt_template(template: PromptTemplate, *, update_existing: bool = False) -> PromptTemplate:
    ensure_storage()
    path = _template_path(template.id)
    now = datetime.now(timezone.utc).isoformat()
    if path.exists():
        if not update_existing:
            raise ValueError("Prompt template already exists. Choose update_existing to overwrite it.")
        existing = _template_from_markdown(path.read_text(encoding="utf-8"), path=path)
        template = PromptTemplate(**{**asdict(template), "created_at": existing.created_at, "updated_at": now, "version": existing.version + 1})
    elif not template.created_at or not template.updated_at:
        template = PromptTemplate(**{**asdict(template), "created_at": now, "updated_at": now})
    _validate_template(template)
    path.write_text(_template_to_markdown(template), encoding="utf-8")
    return template


def duplicate_prompt_template(template_id: str, new_id: str, title: str | None = None) -> PromptTemplate:
    source = get_prompt_template(template_id, include_inactive=True)
    now = datetime.now(timezone.utc).isoformat()
    duplicate = PromptTemplate(**{**asdict(source), "id": new_id, "title": title or f"{source.title} copy", "created_at": now, "updated_at": now, "version": 1, "active": True})
    return save_prompt_template(duplicate, update_existing=False)


def deactivate_prompt_template(template_id: str) -> PromptTemplate:
    template = get_prompt_template(template_id, include_inactive=True)
    updated = PromptTemplate(**{**asdict(template), "active": False, "updated_at": datetime.now(timezone.utc).isoformat(), "version": template.version + 1})
    _template_path(template_id).write_text(_template_to_markdown(updated), encoding="utf-8")
    return updated


def prompt_template_payload(template: PromptTemplate) -> dict[str, Any]:
    payload = _template_payload(template)
    payload["name"] = template.title
    payload["description"] = template.short_description
    return payload


def _template_path(template_id: str) -> Path:
    template_id = str(template_id or "").strip()
    if not PROMPT_ID_PATTERN.fullmatch(template_id):
        raise ValueError("Prompt template id must contain only letters, numbers, hyphens, and underscores.")
    return PROMPT_DIR / f"{template_id}.md"


def _template_from_payload(payload: dict[str, Any]) -> PromptTemplate:
    now = datetime.now(timezone.utc).isoformat()
    title = payload.get("title") or payload.get("name") or payload.get("id") or "Untitled prompt"
    short_description = payload.get("short_description") or payload.get("description") or ""
    return PromptTemplate(
        id=str(payload.get("id") or "").strip(),
        title=str(title).strip(),
        short_description=str(short_description).strip(),
        use_case=str(payload.get("use_case") or short_description or "").strip(),
        task_type=str(payload.get("task_type") or "ontology_suggestion").strip(),
        expected_output_format=str(payload.get("expected_output_format") or "json").strip(),
        input_scope=str(payload.get("input_scope") or "single_literature_item").strip(),
        cost_level=str(payload.get("cost_level") or "low").strip(),
        prompt_text=str(payload.get("prompt_text") or ""),
        created_at=str(payload.get("created_at") or now),
        updated_at=str(payload.get("updated_at") or now),
        version=int(payload.get("version") or 1),
        active=_bool_value(payload.get("active", True)),
    )


def _template_payload(template: PromptTemplate) -> dict[str, Any]:
    return asdict(template)


def _template_to_markdown(template: PromptTemplate) -> str:
    _validate_template(template)
    metadata = {key: value for key, value in _template_payload(template).items() if key != "prompt_text"}
    lines = ["---"]
    for key in [
        "id",
        "title",
        "short_description",
        "use_case",
        "task_type",
        "expected_output_format",
        "input_scope",
        "cost_level",
        "version",
        "active",
        "created_at",
        "updated_at",
    ]:
        lines.append(f"{key}: {_yaml_scalar(metadata[key])}")
    lines.append("---")
    lines.append("")
    lines.append(template.prompt_text.rstrip())
    lines.append("")
    return "\n".join(lines)


def _template_from_markdown(text: str, *, path: Path | None = None) -> PromptTemplate:
    if not text.startswith("---\n"):
        raise ValueError(f"Prompt template {path or ''} is missing YAML front matter.")
    try:
        _, front_matter, body = text.split("---", 2)
    except ValueError as exc:
        raise ValueError(f"Prompt template {path or ''} has malformed YAML front matter.") from exc
    metadata: dict[str, Any] = {}
    for line in front_matter.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"Prompt template {path or ''} has malformed metadata line: {line}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = _parse_yaml_scalar(value.strip())
    missing = sorted(REQUIRED_TEMPLATE_FIELDS - metadata.keys())
    if missing:
        raise ValueError(f"Prompt template {path or ''} is missing metadata fields: {', '.join(missing)}.")
    metadata["prompt_text"] = body.lstrip("\r\n")
    return _template_from_payload(metadata)


def _validate_template(template: PromptTemplate) -> None:
    _template_path(template.id)
    missing = [field for field in REQUIRED_TEMPLATE_FIELDS if getattr(template, field) in (None, "")]
    if missing:
        raise ValueError(f"Prompt template is missing required fields: {', '.join(sorted(missing))}.")
    if not template.prompt_text.strip():
        raise ValueError("Prompt template Markdown body is required.")


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() not in {"false", "0", "no", "off"}


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _parse_yaml_scalar(value: str) -> Any:
    if value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    if value.isdigit():
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value

def load_pricing(session: Session, project: Project | None = None) -> Pricing:
    key = f"ontology_suggestions.pricing.{project.slug}" if project else "ontology_suggestions.pricing"
    setting = session.get(AppSetting, key) or session.get(AppSetting, "ontology_suggestions.pricing")
    if not setting:
        return Pricing()
    payload = json.loads(setting.value)
    return Pricing(**{field: payload.get(field) for field in Pricing.__dataclass_fields__})


def save_pricing(session: Session, payload: dict[str, Any], project: Project | None = None) -> Pricing:
    pricing = Pricing(**{field: payload.get(field) for field in Pricing.__dataclass_fields__})
    key = f"ontology_suggestions.pricing.{project.slug}" if project else "ontology_suggestions.pricing"
    setting = session.get(AppSetting, key)
    if setting:
        setting.value = json.dumps(asdict(pricing))
    else:
        session.add(AppSetting(key=key, value=json.dumps(asdict(pricing))))
    session.commit()
    return pricing


def estimate_cost(input_tokens: int, max_output_tokens: int, pricing: Pricing) -> dict[str, Any]:
    input_cost = (input_tokens / 1_000_000) * pricing.input_cost_per_1m_tokens if pricing.input_cost_per_1m_tokens is not None else None
    output_cost = (max_output_tokens / 1_000_000) * pricing.output_cost_per_1m_tokens if pricing.output_cost_per_1m_tokens is not None else None
    total = None if input_cost is None or output_cost is None else round(input_cost + output_cost, 6)
    projected = None if total is None else round(pricing.estimated_spend_this_month + total, 6)
    threshold = None if pricing.monthly_budget in (None, 0) else pricing.monthly_budget * pricing.warning_threshold
    return {
        "input_tokens": input_tokens,
        "max_output_tokens": max_output_tokens,
        "estimated_cost": total,
        "projected_spend_this_month": projected,
        "monthly_budget": pricing.monthly_budget,
        "warning_threshold": pricing.warning_threshold,
        "budget_warning": bool(projected is not None and threshold is not None and projected >= threshold),
        "message": "Provider billing and real credit balances should be checked in the provider dashboard.",
    }


def project_ontology_path(project: Project) -> Path | None:
    for value in [project.built_ontology_path, project.editable_ontology_path]:
        if value and Path(value).exists():
            return Path(value)
    return None


def project_literature_entries(project: Project) -> dict[str, list[dict[str, Any]]]:
    paths = RepositoryPaths.from_root(Path(project.literature_repository_path or Path(project.local_path) / "literature"))
    tag = (project.ontology_id or "").casefold()

    def tagged(entry: dict[str, Any]) -> bool:
        tags = {str(item).casefold() for item in entry.get("project_tags") or []}
        return not tag or tag in tags

    curated = [entry for entry in list_curated_entries(paths) if tagged(entry)]
    uncurated = [entry for entry in list_entries(paths) if not entry.get("promoted_literature_id") and tagged(entry)]
    return {"curated": curated, "uncurated": uncurated}


def workflow_status(session: Session, project_ref: str | None = None) -> dict[str, Any]:
    project = get_project(session, project_ref)
    literature = project_literature_entries(project)
    ontology_path = project_ontology_path(project)
    return {
        "project": {"id": project.slug, "label": project.name, "ontology_id": project.ontology_id},
        "literature": literature,
        "connected_literature_count": len(literature["curated"]) + len(literature["uncurated"]),
        "ontology_path": str(ontology_path) if ontology_path else None,
        "ontology_context_modes": ["labels_only", "labels_definitions", "labels_definitions_relations", "full"],
        "default_literature_scope": "one",
        "default_ontology_context_mode": "labels_definitions_relations",
    }


def _entry_id(entry: dict[str, Any]) -> str:
    return str(entry.get("canonical_id") or entry.get("id") or entry.get("paper_id") or entry.get("title") or "")


def select_literature(project: Project, scope: str, literature_ids: list[str] | None) -> list[dict[str, Any]]:
    entries = project_literature_entries(project)
    all_entries = [*entries["curated"], *entries["uncurated"]]
    ids = set(literature_ids or [])
    if scope == "all_curated":
        return entries["curated"]
    if scope == "all_uncurated":
        return entries["uncurated"]
    if scope in {"one", "selected"}:
        selected = [entry for entry in all_entries if _entry_id(entry) in ids]
        if scope == "one":
            return selected[:1]
        return selected
    raise ValueError(f"Unsupported literature scope: {scope}")


def build_ontology_context(project: Project, mode: str) -> str:
    path = project_ontology_path(project)
    if not path:
        raise ValueError("The selected project has no readable ontology file.")
    if mode == "full":
        return path.read_text(encoding="utf-8", errors="replace")
    terms = index_ontology_file(path, max_terms=1000)
    lines = []
    for term in terms:
        parts = [term.term_id or term.iri, term.label]
        if mode in {"labels_definitions", "labels_definitions_relations"} and term.definition:
            parts.append(f"definition: {term.definition}")
        if mode == "labels_definitions_relations" and term.relations:
            parts.append(f"relations: {json.dumps(term.relations, ensure_ascii=False)}")
        lines.append(" | ".join(part for part in parts if part))
    return "\n".join(lines)


def build_literature_context(entries: list[dict[str, Any]]) -> str:
    blocks = []
    for entry in entries:
        text = entry.get("literature_markdown") or entry.get("markdown") or entry.get("content") or ""
        if not text and entry.get("markdown_file"):
            text = Path(entry["markdown_file"]).read_text(encoding="utf-8", errors="replace")
        blocks.append(f"## Literature item {_entry_id(entry)}\nTitle: {entry.get('title') or 'Untitled'}\n\n{text}")
    return "\n\n".join(blocks)


def target_schema() -> dict[str, Any]:
    return {
        "literature_id": "string",
        "project_id": "string",
        "ontology_id": "string",
        "prompt_template_id": "string",
        "suggestions": [
            {
                "suggestion_type": "class | relation | synonym | definition | annotation | duplicate_warning",
                "label": "string",
                "proposed_parent": "string or null",
                "definition": "string or null",
                "relation": "string or null",
                "target": "string or null",
                "evidence_quote": "string",
                "evidence_location": "string or null",
                "confidence": "low | medium | high",
                "rationale": "string",
                "requires_human_check": True,
            }
        ],
    }


def build_prompt(
    *,
    project: Project,
    template: PromptTemplate,
    prompt_text: str,
    literature_entries: list[dict[str, Any]],
    ontology_context: str,
    ontology_context_mode: str,
    cheap_test: bool = False,
) -> str:
    if cheap_test:
        literature_context = "Dummy literature: Protein precipitation can occur after adding ammonium sulfate."
        ontology_context = "PPO:0000001 | protein precipitation | definition: a precipitation process involving protein"
        schema = {"status": "ok", "task": "ontology_suggestion_test", "suggestions": []}
    else:
        literature_context = build_literature_context(literature_entries)
        schema = target_schema()
    return "\n".join(
        [
            f"Prompt template id: {template.id}",
            f"Task type: {template.task_type}",
            f"Project id: {project.slug}",
            f"Ontology id: {project.ontology_id}",
            f"Ontology context mode: {ontology_context_mode}",
            "",
            "Template instructions:",
            prompt_text,
            "",
            "Return strict JSON matching this target schema:",
            json.dumps(schema, indent=2),
            "",
            "Ontology context:",
            ontology_context,
            "",
            "Literature context:",
            literature_context,
        ]
    )


def validate_test_payload(payload: Any) -> dict[str, Any]:
    if payload != {"status": "ok", "task": "ontology_suggestion_test", "suggestions": []}:
        raise ValueError("Cheap function test response did not match the required minimal JSON.")
    return payload


def validate_suggestion_payload(payload: Any, *, project: Project, template_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("suggestions"), list):
        raise ValueError("Ontology suggestion response must contain a suggestions array.")
    required = {"suggestion_type", "label", "evidence_quote", "confidence", "rationale", "requires_human_check"}
    allowed_types = {"class", "relation", "synonym", "definition", "annotation", "duplicate_warning"}
    allowed_confidence = {"low", "medium", "high"}
    for index, suggestion in enumerate(payload["suggestions"], start=1):
        if not isinstance(suggestion, dict):
            raise ValueError(f"Suggestion {index} must be an object.")
        missing = sorted(required - suggestion.keys())
        if missing:
            raise ValueError(f"Suggestion {index} is missing required fields: {', '.join(missing)}.")
        if suggestion["suggestion_type"] not in allowed_types:
            raise ValueError(f"Suggestion {index} has unsupported suggestion_type.")
        if suggestion["confidence"] not in allowed_confidence:
            raise ValueError(f"Suggestion {index} has unsupported confidence.")
        if suggestion["requires_human_check"] is not True:
            raise ValueError(f"Suggestion {index} must require human check.")
    payload.setdefault("project_id", project.slug)
    payload.setdefault("ontology_id", project.ontology_id)
    payload.setdefault("prompt_template_id", template_id)
    return payload


def _result_text(result: str | LlmTextResult) -> tuple[str, dict[str, Any] | None]:
    if isinstance(result, LlmTextResult):
        usage = getattr(result, "usage", None)
        return result.text, usage
    return result, None


def preview_run(
    session: Session,
    *,
    project_ref: str,
    prompt_template_id: str,
    literature_scope: str = "one",
    literature_ids: list[str] | None = None,
    ontology_context_mode: str = "labels_definitions_relations",
    prompt_text: str | None = None,
) -> dict[str, Any]:
    project = get_project(session, project_ref)
    template = get_prompt_template(prompt_template_id)
    entries = select_literature(project, literature_scope, literature_ids)
    if not entries:
        raise ValueError("No literature entries match the selected scope.")
    ontology_context = build_ontology_context(project, ontology_context_mode)
    prompt = build_prompt(
        project=project,
        template=template,
        prompt_text=prompt_text or template.prompt_text,
        literature_entries=entries,
        ontology_context=ontology_context,
        ontology_context_mode=ontology_context_mode,
    )
    config = llm_config(session)
    tokens = estimate_input_size(prompt, system_prompt=SYSTEM_PROMPT)["approx_tokens"]
    pricing = load_pricing(session, project)
    return {
        "project": {"id": project.slug, "label": project.name},
        "literature_ids": [_entry_id(entry) for entry in entries],
        "literature_count": len(entries),
        "ontology_context_mode": ontology_context_mode,
        "prompt_template_id": template.id,
        "prompt_template_title": template.title,
        "prompt_template_version": template.version,
        "estimated_input_tokens": tokens,
        "max_output_tokens": config.max_output_tokens,
        "cost": estimate_cost(tokens, config.max_output_tokens, pricing),
        "requires_confirmation": len(entries) > 1,
        "prompt": prompt,
    }


def cheap_function_test(
    session: Session,
    *,
    project_ref: str,
    prompt_template_id: str,
    prompt_text: str | None = None,
    caller: SuggestionCaller | None = None,
    show_response_preview: bool = True,
    debug: bool = False,
) -> dict[str, Any]:
    project = get_project(session, project_ref)
    template = get_prompt_template(prompt_template_id)
    config = llm_config(session)
    diagnostics = run_api_function_test(
        config=config,
        prompt_template_id=template.id,
        task_type=template.task_type,
        caller=caller,
        show_response_preview=show_response_preview,
        debug=debug,
    )
    payload = diagnostic_payload(diagnostics)
    payload["ok"] = diagnostics.schema_valid
    payload["project_id"] = project.slug
    payload["prompt_template_id"] = template.id
    payload["payload"] = {"status": "ok", "task": "ontology_suggestion_test", "suggestions": []} if diagnostics.schema_valid else None
    return payload


def run_suggestions(
    session: Session,
    *,
    project_ref: str,
    prompt_template_id: str,
    literature_scope: str,
    literature_ids: list[str],
    ontology_context_mode: str,
    prompt_text: str | None = None,
    confirmed: bool = False,
    caller: SuggestionCaller | None = None,
) -> dict[str, Any]:
    preview = preview_run(
        session,
        project_ref=project_ref,
        prompt_template_id=prompt_template_id,
        literature_scope=literature_scope,
        literature_ids=literature_ids,
        ontology_context_mode=ontology_context_mode,
        prompt_text=prompt_text,
    )
    if preview["requires_confirmation"] and not confirmed:
        raise ValueError("Multi-paper ontology suggestion runs require explicit confirmation.")
    project = get_project(session, project_ref)
    template = get_prompt_template(prompt_template_id)
    config = llm_config(session)
    if not config.provider or not config.resolved_api_key:
        raise LlmUnavailableError("No API key was found. Configure an LLM provider before running suggestions.")
    raw = ""
    usage = None
    payload = None
    error = None
    status = "ok"
    try:
        raw, usage = _result_text(caller(preview["prompt"], config) if caller else generate_text(preview["prompt"], system_prompt=SYSTEM_PROMPT, config=config))
        payload = validate_suggestion_payload(json.loads(raw), project=project, template_id=prompt_template_id)
    except (json.JSONDecodeError, ValueError, LlmClientError) as exc:
        status = "failed"
        error = str(exc)
    run_file = _write_run_file(
        {
            "run_type": "suggestion_run",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "provider": normalize_provider_id(config.provider),
            "model": config.model,
            "project_id": project.slug,
            "literature_ids": preview["literature_ids"],
            "ontology_context_mode": ontology_context_mode,
            "prompt_template_id": template.id,
            "prompt_template_title": template.title,
            "prompt_template_version": template.version,
            "estimated_tokens": preview["estimated_input_tokens"],
            "reported_token_usage": usage,
            "estimated_cost": preview["cost"],
            "error": error,
            "raw_response": raw,
            "payload": payload,
            "debug_prompt_logged": False,
        }
    )
    if status != "ok":
        raise ValueError(f"Ontology suggestion response was not valid: {error}")
    curation_run = CurationRun(
        project_id=project.id,
        name=f"Ontology suggestions {run_file['run_id']}",
        model=config.model,
        prompt_strategy="ontology_suggestions",
        context_configuration_json=json.dumps(
            {
                "workflow_run_id": run_file["run_id"],
                "literature_ids": preview["literature_ids"],
                "ontology_context_mode": ontology_context_mode,
                "prompt_template_id": template.id,
                "prompt_template_title": template.title,
                "prompt_template_version": template.version,
            }
        ),
        prompt_text=prompt_text or template.prompt_text,
        literature_snapshot_path=None,
        ontology_snapshot_path=str(project_ontology_path(project) or ""),
        raw_output=raw,
        status="created",
    )
    session.add(curation_run)
    session.flush()
    for item in payload["suggestions"]:
        session.add(
            Suggestion(
                project_id=project.id,
                curation_run_id=curation_run.id,
                suggestion_type=item["suggestion_type"],
                label=item["label"],
                definition=item.get("definition"),
                parent_class=item.get("proposed_parent"),
                relation=item.get("relation"),
                target=item.get("target"),
                evidence_text=item.get("evidence_quote"),
                evidence_source=item.get("evidence_location"),
                evidence_json=json.dumps(
                    [{"quote": item.get("evidence_quote"), "location": item.get("evidence_location")}]
                ),
                confidence=item.get("confidence"),
                raw_llm_output=json.dumps(item),
            )
        )
    session.commit()
    return {
        "ok": True,
        "run_id": run_file["run_id"],
        "curation_run_id": curation_run.id,
        "suggestion_count": len(payload["suggestions"]),
        "output_path": run_file["path"],
        "preview": {key: value for key, value in preview.items() if key != "prompt"},
    }


def list_runs() -> list[dict[str, Any]]:
    ensure_storage()
    runs = []
    for path in sorted(RUN_DIR.glob("*.json"), reverse=True):
        payload = json.loads(path.read_text(encoding="utf-8"))
        runs.append({key: payload.get(key) for key in ["run_id", "run_type", "timestamp", "status", "project_id", "prompt_template_id", "prompt_template_title", "prompt_template_version", "error"]})
    return runs


def show_run(run_id: str) -> dict[str, Any]:
    ensure_storage()
    path = RUN_DIR / f"{run_id}.json"
    if not path.exists():
        raise ValueError(f"Unknown ontology suggestion run: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def review_suggestion_to_candidate(
    session: Session,
    *,
    suggestion_id: int,
    status: str,
    reviewer: str | None = None,
    comment: str | None = None,
    edited: dict[str, Any] | None = None,
) -> dict[str, Any]:
    suggestion = session.get(Suggestion, suggestion_id)
    if not suggestion:
        raise ValueError("Suggestion was not found.")
    review = add_review(
        session,
        suggestion,
        status=status,
        reviewer=reviewer,
        comment=comment,
        edited_label=(edited or {}).get("label"),
        edited_definition=(edited or {}).get("definition"),
        edited_parent_class=(edited or {}).get("proposed_parent"),
        edited_relation=(edited or {}).get("relation"),
        edited_target=(edited or {}).get("target"),
    )
    candidate_id = None
    if status in {"accepted", "edited"}:
        candidate = _candidate_from_suggestion(session, suggestion, edited or {})
        candidate_id = candidate.id
    session.commit()
    return {"ok": True, "review_id": review.id, "candidate_id": candidate_id}


def _candidate_from_suggestion(session: Session, suggestion: Suggestion, edited: dict[str, Any]) -> CandidateTermRecord:
    label = edited.get("label") or suggestion.label
    document = _document_for_suggestion(session, suggestion)
    existing = session.scalar(
        select(CandidateTermRecord).where(
            CandidateTermRecord.document_id == document.id,
            CandidateTermRecord.normalized_label == normalize_label(label),
        )
    )
    if existing:
        return existing
    confidence_map = {"low": 0.33, "medium": 0.66, "high": 0.9}
    candidate = CandidateTermRecord(
        project_id=suggestion.project_id,
        candidate_id=build_candidate_id(document.id, label),
        document_id=document.id,
        label=label,
        normalized_label=normalize_label(label),
        proposed_definition=edited.get("definition") or suggestion.definition,
        synonyms_json="[]",
        proposed_parent=edited.get("proposed_parent") or suggestion.parent_class,
        confidence_score=confidence_map.get(suggestion.confidence or "medium", 0.66),
        review_status=ReviewStatus.NEW.value,
        evidence_json=suggestion.evidence_json or "[]",
        source_evidence=suggestion.evidence_text,
        curator_rationale=json.loads(suggestion.raw_llm_output or "{}").get("rationale") if suggestion.raw_llm_output else None,
    )
    session.add(candidate)
    session.flush()
    return candidate


def _document_for_suggestion(session: Session, suggestion: Suggestion) -> LiteratureDocument:
    path = f"ontology_suggestion:{suggestion.id}"
    existing = session.scalar(select(LiteratureDocument).where(LiteratureDocument.path == path))
    if existing:
        return existing
    document = LiteratureDocument(
        project_id=suggestion.project_id,
        path=path,
        filename=f"ontology-suggestion-{suggestion.id}.json",
        suffix=".json",
        size_bytes=0,
        title="Ontology suggestion review",
        content=suggestion.evidence_text or "",
        extraction_status="ontology_suggestion_review",
    )
    session.add(document)
    session.flush()
    return document


def _write_run_file(payload: dict[str, Any]) -> dict[str, str]:
    ensure_storage()
    run_id = payload.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    payload["run_id"] = run_id
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    path = RUN_DIR / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log_path = LOG_DIR / "runs.jsonl"
    log_payload = {key: payload.get(key) for key in ["run_id", "timestamp", "run_type", "status", "provider", "model", "project_id", "prompt_template_id", "prompt_template_title", "prompt_template_version", "estimated_tokens", "reported_token_usage", "estimated_cost", "error"]}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(log_payload) + "\n")
    return {"run_id": run_id, "path": str(path)}
