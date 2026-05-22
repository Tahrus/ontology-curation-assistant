from pydantic import BaseModel, Field


class ExtractionMetadata(BaseModel):
    provider: str
    model: str
    prompt_name: str
    prompt_version: str
    temperature: float | None = None


class ExtractedClaim(BaseModel):
    claim_type: str
    text: str
    evidence_quote: str
    direct_or_inferred: str = Field(pattern="^(direct|inferred|contextual)$")
    confidence_score: float = Field(ge=0.0, le=1.0)
    uncertainty_note: str | None = None

