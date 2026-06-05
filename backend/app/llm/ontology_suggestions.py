from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.app.llm.service import LlmUnavailableError, _call_openai_compatible
from backend.app.literature.repository import load_llm_ready_repository_with_diagnostics
from backend.app.services.runtime_config import LlmRuntimeConfig


SuggestionCaller = Callable[[str, LlmRuntimeConfig], str]


@dataclass(frozen=True)
class OntologySuggestionTestResult:
    ok: bool
    dry_run: bool
    output_path: Path
    literature_count: int
    suggestion_count: int
    skipped_files: list[dict[str, str]]
    message: str


def build_literature_export(repository_path: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    result = load_llm_ready_repository_with_diagnostics(repository_path)
    records = []
    for paper in result.papers:
        metadata = paper.get("metadata") or {}
        records.append(
            {
                "id": paper.get("id") or metadata.get("id"),
                "title": paper.get("title") or metadata.get("title"),
                "authors": paper.get("authors") or metadata.get("authors") or [],
                "year": paper.get("year") or metadata.get("year"),
                "doi": paper.get("doi") or metadata.get("doi"),
                "pmid": paper.get("pmid") or metadata.get("pmid"),
                "pmcid": metadata.get("pmcid"),
                "zotero_key": metadata.get("zotero_key") or metadata.get("id"),
                "abstract": paper.get("abstract") or "",
                "relevant_text": paper.get("ontology_relevant_information") or "",
                "source_file": paper.get("source_file"),
            }
        )
    return records, result.skipped_files


def build_ontology_suggestion_prompt(records: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            "Return only JSON with this schema:",
            '{"suggestions":[{"proposed_label":"string","definition":"string","synonyms":["string"],'
            '"parent_class":"string or null","source_literature_ids":["string"],'
            '"confidence":"number 0..1","rationale":"string"}]}',
            "",
            "Literature export:",
            json.dumps(records, ensure_ascii=False, indent=2),
        ]
    )


def validate_ontology_suggestion_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("suggestions"), list):
        raise ValueError("Ontology suggestion response must contain a suggestions list.")
    for index, suggestion in enumerate(payload["suggestions"], start=1):
        if not isinstance(suggestion, dict):
            raise ValueError(f"Suggestion {index} must be an object.")
        for key in ["proposed_label", "definition", "synonyms", "source_literature_ids", "confidence", "rationale"]:
            if key not in suggestion:
                raise ValueError(f"Suggestion {index} is missing required field '{key}'.")
        if not isinstance(suggestion["synonyms"], list):
            raise ValueError(f"Suggestion {index} field 'synonyms' must be a list.")
        if not isinstance(suggestion["source_literature_ids"], list):
            raise ValueError(f"Suggestion {index} field 'source_literature_ids' must be a list.")
        confidence = suggestion["confidence"]
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            raise ValueError(f"Suggestion {index} field 'confidence' must be a number from 0 to 1.")
    return payload


def run_ontology_suggestion_test(
    *,
    config: LlmRuntimeConfig,
    repository_path: Path | None = None,
    output_path: Path | None = None,
    dry_run: bool = True,
    caller: SuggestionCaller | None = None,
) -> OntologySuggestionTestResult:
    records, skipped = build_literature_export(repository_path)
    if not records:
        raise ValueError("No valid literature Markdown files are available for ontology suggestions.")
    prompt = build_ontology_suggestion_prompt(records)
    if dry_run:
        payload: dict[str, Any] = {"suggestions": []}
        raw_response = None
    else:
        if not config.provider or not config.api_key:
            raise LlmUnavailableError("LLM ontology suggestion test requires configured provider and API key.")
        if config.provider.casefold() not in {"openai", "openai-compatible"}:
            raise LlmUnavailableError("Only OpenAI-compatible LLM providers are supported.")
        if caller is not None:
            raw_response = caller(prompt, config)
        else:
            base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
            raw_response = _call_openai_compatible(base_url, config.api_key, config.model or "gpt-4o-mini", prompt)
        payload = validate_ontology_suggestion_payload(json.loads(raw_response))

    destination = output_path or Path("literature") / "ontology_suggestions" / "ontology_suggestion_test.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "dry_run": dry_run,
                "literature_count": len(records),
                "skipped_files": skipped,
                "prompt": prompt,
                "raw_response": raw_response,
                "payload": payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return OntologySuggestionTestResult(
        ok=True,
        dry_run=dry_run,
        output_path=destination,
        literature_count=len(records),
        suggestion_count=len(payload["suggestions"]),
        skipped_files=skipped,
        message="Ontology suggestion test completed.",
    )
