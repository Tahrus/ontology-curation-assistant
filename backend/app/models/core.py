from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewStatus(StrEnum):
    NEW = "new"
    IN_REVIEW = "in_review"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    APPROVED = "approved"
    APPROVED_WITH_EDITS = "approved_with_edits"
    REJECTED = "rejected"
    PERMANENTLY_REJECTED = "permanently_rejected"
    DEFERRED = "deferred"
    EXPORTED_TO_ODK = "exported_to_odk"
    ODK_VALIDATION_FAILED = "odk_validation_failed"
    MERGED = "merged"


class Evidence(BaseModel):
    document_id: str
    quoted_text: str
    section_title: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    direct_or_inferred: str = Field(pattern="^(direct|inferred|contextual)$")


class CandidateTerm(BaseModel):
    candidate_id: str
    label: str
    proposed_definition: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    proposed_parent: str | None = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.NEW
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
