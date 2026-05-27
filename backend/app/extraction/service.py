import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.extraction.parser import CandidateExtractionResponse, CandidatePayload
from backend.app.extraction.prompts import PROMPT_NAME, PROMPT_VERSION
from backend.app.models.core import ReviewStatus
from backend.app.models.db import CandidateTermRecord, ExtractionRun


def normalize_label(label: str) -> str:
    return " ".join(label.casefold().split())


def build_candidate_id(document_id: int, label: str) -> str:
    digest = hashlib.sha1(f"{document_id}:{normalize_label(label)}".encode("utf-8")).hexdigest()
    return f"CAND:{digest[:12]}"


def candidate_to_record(
    candidate: CandidatePayload,
    *,
    document_id: int,
    extraction_run_id: int | None,
) -> CandidateTermRecord:
    evidence = [
        evidence.model_dump(mode="json")
        for evidence in candidate.evidence
    ]
    return CandidateTermRecord(
        candidate_id=build_candidate_id(document_id, candidate.label),
        document_id=document_id,
        extraction_run_id=extraction_run_id,
        label=candidate.label,
        normalized_label=normalize_label(candidate.label),
        proposed_definition=candidate.proposed_definition,
        synonyms_json=json.dumps(candidate.synonyms),
        proposed_parent=candidate.proposed_parent,
        confidence_score=candidate.confidence_score,
        review_status=ReviewStatus.NEW.value,
        evidence_json=json.dumps(evidence),
    )


def create_extraction_run(
    session: Session,
    *,
    document_id: int,
    provider: str,
    model: str,
    raw_response: str,
) -> ExtractionRun:
    run = ExtractionRun(
        document_id=document_id,
        provider=provider,
        model=model,
        prompt_name=PROMPT_NAME,
        prompt_version=PROMPT_VERSION,
        raw_response=raw_response,
    )
    session.add(run)
    session.flush()
    return run


def persist_candidates(
    session: Session,
    *,
    document_id: int,
    response: CandidateExtractionResponse,
    provider: str,
    model: str,
    raw_response: str,
) -> tuple[int, int]:
    run = create_extraction_run(
        session,
        document_id=document_id,
        provider=provider,
        model=model,
        raw_response=raw_response,
    )

    inserted = 0
    skipped = 0

    for candidate in response.candidates:
        normalized = normalize_label(candidate.label)
        existing = session.scalar(
            select(CandidateTermRecord).where(
                CandidateTermRecord.document_id == document_id,
                CandidateTermRecord.normalized_label == normalized,
            )
        )
        if existing is not None:
            skipped += 1
            continue

        session.add(
            candidate_to_record(
                candidate,
                document_id=document_id,
                extraction_run_id=run.id,
            )
        )
        session.flush()
        inserted += 1

    session.commit()
    return inserted, skipped
