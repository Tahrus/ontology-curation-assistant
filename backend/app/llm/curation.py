from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.app.config import get_settings
from backend.app.llm.service import LlmUnavailableError, _call_openai_compatible
from backend.app.services.runtime_config import LlmRuntimeConfig


CURATION_PROMPT_SETTING_KEY = "curation_prompt_template"

DEFAULT_CURATION_PROMPT = """You are assisting ontology curation.

You will receive two inputs:

1. Literature evidence from combined_literature.md
2. The current ontology state as an OBO file

Task:
Analyze the literature evidence and compare it against the current ontology.

Suggest candidate additions and improvements for the ontology, including:
- new ontology classes
- improved definitions for existing or proposed classes
- synonyms
- parent-child hierarchy relations
- object/property relations where supported by evidence
- cross-references or literature references
- possible obsolete, duplicate, or ambiguous terms

Rules:
- Do not invent unsupported ontology entries.
- Every suggested class or relation must cite supporting literature evidence from the provided literature input.
- Do not suggest entries already present in the ontology unless you are suggesting a specific improvement.
- Preserve existing ontology identifiers unless proposing a new candidate without an assigned ID.
- Return machine-readable JSON only.
- Include confidence values.
- Include rationale for every suggestion.
- Distinguish between high-confidence suggestions and speculative suggestions.

Expected JSON response schema:

{
  "suggestions": [
    {
      "suggestion_type": "new_class | improved_definition | synonym | hierarchy_relation | object_relation | xref | obsolete_or_merge_candidate",
      "proposed_label": "string",
      "existing_ontology_id": "string or null",
      "proposed_definition": "string or null",
      "synonyms": ["string"],
      "parent_class": "string or null",
      "relations": [
        {
          "relation_type": "string",
          "target": "string",
          "evidence": "string"
        }
      ],
      "source_literature_ids": ["string"],
      "supporting_quotes_or_summaries": ["string"],
      "confidence": "number between 0 and 1",
      "rationale": "string"
    }
  ],
  "warnings": [
    {
      "warning_type": "string",
      "message": "string"
    }
  ]
}
"""

OUTPUT_REQUIREMENT = "Return valid JSON only according to the schema above."


class CurationInputError(ValueError):
    pass


class CurationResponseError(ValueError):
    pass


SuggestionCaller = Callable[[str, LlmRuntimeConfig], str]


@dataclass(frozen=True)
class CurationInputs:
    prompt: str
    ontology_path: Path
    ontology_content: str
    literature_path: Path
    literature_content: str


@dataclass(frozen=True)
class CurationRunResult:
    ok: bool
    output_dir: Path
    request_path: Path
    response_path: Path | None
    raw_response_path: Path | None
    suggestion_count: int
    warning_count: int
    chunk_count: int
    oversized: bool
    payload: dict[str, Any] = field(default_factory=dict)
    message: str = "Ontology curation suggestions completed."


def load_curation_inputs(
    *,
    prompt: str,
    ontology_path: Path | None,
    literature_path: Path,
) -> CurationInputs:
    if not prompt.strip():
        raise CurationInputError("Curation prompt is empty. Save or reset the curation prompt before running.")
    if ontology_path is None:
        raise CurationInputError("No existing ontology file is selected. Select an .obo file on the Existing Ontology page.")
    if not ontology_path.exists():
        raise CurationInputError(f"Selected ontology file was not found: {ontology_path}")
    if not ontology_path.is_file():
        raise CurationInputError(f"Selected ontology path is not a file: {ontology_path}")
    if ontology_path.suffix.casefold() != ".obo":
        raise CurationInputError(f"Selected ontology file must be an .obo file for curation: {ontology_path}")
    try:
        ontology_content = ontology_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CurationInputError(f"Selected ontology file could not be read: {exc}") from exc
    if not ontology_content.strip():
        raise CurationInputError(f"Selected ontology file is empty: {ontology_path}")

    if not literature_path.exists():
        raise CurationInputError(
            f"combined_literature.md was not found at {literature_path}. Run the Zotero literature pipeline first."
        )
    if not literature_path.is_file():
        raise CurationInputError(f"Configured combined literature path is not a file: {literature_path}")
    try:
        literature_content = literature_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CurationInputError(f"combined_literature.md could not be read: {exc}") from exc
    if not literature_content.strip():
        raise CurationInputError(
            f"combined_literature.md is empty at {literature_path}. Run the Zotero literature pipeline first."
        )

    return CurationInputs(
        prompt=prompt,
        ontology_path=ontology_path,
        ontology_content=ontology_content,
        literature_path=literature_path,
        literature_content=literature_content,
    )


def assemble_curation_prompt(inputs: CurationInputs, *, literature_content: str | None = None) -> str:
    return "\n\n".join(
        [
            "# CURATION PROMPT",
            inputs.prompt.strip(),
            "# CURRENT ONTOLOGY OBO",
            inputs.ontology_content.strip(),
            "# LITERATURE EVIDENCE: combined_literature.md",
            (literature_content if literature_content is not None else inputs.literature_content).strip(),
            "# OUTPUT REQUIREMENT",
            OUTPUT_REQUIREMENT,
        ]
    )


def validate_curation_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CurationResponseError("Curation response must be a JSON object.")
    suggestions = payload.get("suggestions")
    warnings = payload.get("warnings", [])
    if not isinstance(suggestions, list):
        raise CurationResponseError("Curation response must contain a suggestions list.")
    if not isinstance(warnings, list):
        raise CurationResponseError("Curation response warnings must be a list.")
    required = {
        "suggestion_type",
        "proposed_label",
        "existing_ontology_id",
        "proposed_definition",
        "synonyms",
        "parent_class",
        "relations",
        "source_literature_ids",
        "supporting_quotes_or_summaries",
        "confidence",
        "rationale",
    }
    for index, suggestion in enumerate(suggestions, start=1):
        if not isinstance(suggestion, dict):
            raise CurationResponseError(f"Suggestion {index} must be an object.")
        missing = sorted(required - set(suggestion))
        if missing:
            raise CurationResponseError(f"Suggestion {index} is missing fields: {', '.join(missing)}")
        confidence = suggestion.get("confidence")
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            raise CurationResponseError(f"Suggestion {index} confidence must be a number between 0 and 1.")
    return {"suggestions": suggestions, "warnings": warnings}


def run_curation_suggestion_workflow(
    *,
    prompt: str,
    ontology_path: Path | None,
    literature_path: Path,
    config: LlmRuntimeConfig,
    output_dir: Path | None = None,
    max_context_chars: int | None = None,
    caller: SuggestionCaller | None = None,
) -> CurationRunResult:
    if not config.provider or not config.api_key:
        raise LlmUnavailableError("LLM configuration is missing. Configure provider and API key before curation.")
    if config.provider.casefold() not in {"openai", "openai-compatible"}:
        raise LlmUnavailableError("Only OpenAI-compatible LLM providers are supported for curation.")

    inputs = load_curation_inputs(prompt=prompt, ontology_path=ontology_path, literature_path=literature_path)
    limit = max_context_chars or get_settings().llm_context_char_limit
    chunks = _curation_chunks(inputs, limit)
    destination = output_dir or Path("literature") / "curation_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination.mkdir(parents=True, exist_ok=True)

    request_records = []
    aggregated: dict[str, list[Any]] = {"suggestions": [], "warnings": []}
    raw_response_path = destination / "raw_response.txt"
    try:
        for index, chunk in enumerate(chunks, start=1):
            final_prompt = assemble_curation_prompt(inputs, literature_content=chunk)
            request_records.append(
                {
                    "chunk": index,
                    "prompt": final_prompt,
                    "ontology_path": str(inputs.ontology_path),
                    "literature_path": str(inputs.literature_path),
                }
            )
            raw = _call_curation_llm(final_prompt, config, caller)
            try:
                payload = validate_curation_response(json.loads(raw))
            except (json.JSONDecodeError, CurationResponseError) as exc:
                raw_response_path.write_text(raw, encoding="utf-8")
                _write_request_trace(destination / "request.json", request_records, config)
                raise CurationResponseError(f"LLM curation response was not valid JSON: {exc}") from exc
            aggregated["suggestions"].extend(payload["suggestions"])
            aggregated["warnings"].extend(payload["warnings"])
    finally:
        if request_records:
            _write_request_trace(destination / "request.json", request_records, config)

    response_path = destination / "response.json"
    response_path.write_text(json.dumps(aggregated, ensure_ascii=False, indent=2), encoding="utf-8")
    return CurationRunResult(
        ok=True,
        output_dir=destination,
        request_path=destination / "request.json",
        response_path=response_path,
        raw_response_path=raw_response_path if raw_response_path.exists() else None,
        suggestion_count=len(aggregated["suggestions"]),
        warning_count=len(aggregated["warnings"]),
        chunk_count=len(chunks),
        oversized=len(chunks) > 1,
        payload=aggregated,
    )


def _call_curation_llm(prompt: str, config: LlmRuntimeConfig, caller: SuggestionCaller | None) -> str:
    if caller is not None:
        return caller(prompt, config)
    base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
    return _call_openai_compatible(base_url, config.api_key or "", config.model or "gpt-4o-mini", prompt)


def _curation_chunks(inputs: CurationInputs, max_context_chars: int) -> list[str]:
    full_prompt = assemble_curation_prompt(inputs)
    if len(full_prompt) <= max_context_chars:
        return [inputs.literature_content]
    overhead = len(assemble_curation_prompt(inputs, literature_content=""))
    available = max_context_chars - overhead - 200
    if available < 1000:
        raise CurationInputError(
            "The saved prompt plus selected ontology exceed the configured model context limit before literature is added."
        )
    return _split_text(inputs.literature_content, available)


def _split_text(text: str, max_chars: int) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) > max_chars:
            chunks.extend(paragraph[index:index + max_chars] for index in range(0, len(paragraph), max_chars))
        else:
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _write_request_trace(path: Path, records: list[dict[str, Any]], config: LlmRuntimeConfig) -> None:
    path.write_text(
        json.dumps(
            {
                "provider": config.provider,
                "model": config.model,
                "base_url": config.base_url,
                "chunks": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
