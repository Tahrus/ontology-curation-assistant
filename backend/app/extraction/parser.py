import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class CandidateEvidencePayload(BaseModel):
    quoted_text: str = Field(min_length=1)
    section_title: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    direct_or_inferred: str = Field(pattern="^(direct|inferred|contextual)$")

    @field_validator("quoted_text")
    @classmethod
    def quoted_text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("evidence quoted_text must not be empty")
        return stripped


class CandidatePayload(BaseModel):
    label: str = Field(min_length=1)
    proposed_definition: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    proposed_parent: str | None = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence: list[CandidateEvidencePayload] = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def label_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("candidate label must not be empty")
        return stripped

    @field_validator("synonyms")
    @classmethod
    def clean_synonyms(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class CandidateExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[CandidatePayload]


class CandidateExtractionParseError(ValueError):
    pass


def parse_candidate_response(raw_response: str) -> CandidateExtractionResponse:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise CandidateExtractionParseError(f"Malformed JSON response: {exc.msg}") from exc

    try:
        return CandidateExtractionResponse.model_validate(payload)
    except ValidationError as exc:
        raise CandidateExtractionParseError(f"Invalid candidate extraction response: {exc}") from exc
