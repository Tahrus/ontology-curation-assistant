from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from backend.app.extraction.parser import CandidateExtractionResponse, CandidatePayload
from backend.app.extraction.prompts import build_candidate_extraction_prompt
from backend.app.services.runtime_config import LlmRuntimeConfig


class LlmUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtractionResult:
    response: CandidateExtractionResponse
    provider: str
    model: str
    raw_response: str
    used_llm: bool
    message: str


def mock_extract_candidates(
    document_text: str,
    *,
    guidance: str | None = None,
) -> CandidateExtractionResponse:
    seed = guidance or document_text
    phrases = _candidate_phrases(seed)
    if not phrases and document_text:
        phrases = _candidate_phrases(document_text)
    if not phrases:
        phrases = ["manual ontology candidate"]

    candidates = []
    for phrase in phrases[:3]:
        evidence = _evidence_for_phrase(document_text, phrase) or guidance or phrase
        candidates.append(
            CandidatePayload(
                label=phrase,
                proposed_definition=f"A curator-reviewed ontology candidate related to {phrase}.",
                synonyms=[],
                proposed_parent="ontology candidate",
                confidence_score=0.42,
                evidence=[
                    {
                        "quoted_text": evidence,
                        "section_title": "mock extraction",
                        "page_number": None,
                        "char_start": None,
                        "char_end": None,
                        "direct_or_inferred": "contextual",
                    }
                ],
            )
        )

    return CandidateExtractionResponse(candidates=candidates)


def extract_candidates_with_optional_llm(
    document_text: str,
    *,
    document_id: int,
    filename: str,
    config: LlmRuntimeConfig,
    guidance: str | None = None,
    use_llm: bool = False,
) -> ExtractionResult:
    if not use_llm:
        response = mock_extract_candidates(document_text, guidance=guidance)
        return ExtractionResult(
            response=response,
            provider="mock",
            model="deterministic-mock",
            raw_response=response.model_dump_json(),
            used_llm=False,
            message="Mock extraction used. Configure an LLM and enable LLM extraction for model output.",
        )

    if not config.provider or not config.api_key:
        raise LlmUnavailableError("LLM extraction is unavailable because provider or API key is missing.")

    if config.provider.casefold() not in {"openai", "openai-compatible"}:
        raise LlmUnavailableError("Only OpenAI-compatible LLM providers are supported in this prototype.")

    model = config.model or "gpt-4o-mini"
    base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
    prompt = build_candidate_extraction_prompt(
        f"Curator guidance:\n{guidance}\n\n{document_text}" if guidance else document_text,
        document_id=document_id,
        filename=filename,
    )
    raw_response = _call_openai_compatible(base_url, config.api_key, model, prompt)
    payload = CandidateExtractionResponse.model_validate(json.loads(raw_response))
    return ExtractionResult(
        response=payload,
        provider=config.provider,
        model=model,
        raw_response=raw_response,
        used_llm=True,
        message="LLM extraction completed.",
    )


def _call_openai_compatible(base_url: str, api_key: str, model: str, prompt: str) -> str:
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only the requested JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        return str(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmUnavailableError("LLM response did not contain chat completion content.") from exc


def _candidate_phrases(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", text.casefold())
    stop = {
        "candidate",
        "candidates",
        "curator",
        "extract",
        "focus",
        "source",
        "terms",
        "ontology",
        "paper",
        "from",
        "with",
        "that",
        "this",
    }
    filtered = [word for word in words if word not in stop]
    phrases = []
    for index in range(max(0, len(filtered) - 1)):
        phrase = f"{filtered[index]} {filtered[index + 1]}"
        if phrase not in phrases:
            phrases.append(phrase)
    return phrases[:5]


def _evidence_for_phrase(text: str, phrase: str) -> str | None:
    if not text:
        return None
    first_word = phrase.split()[0]
    start = text.casefold().find(first_word)
    if start == -1:
        return text[:300]
    return text[max(0, start - 80): start + 220].strip()
