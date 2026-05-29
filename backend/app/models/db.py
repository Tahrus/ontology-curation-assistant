from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class LiteratureDocument(Base):
    __tablename__ = "literature_documents"
    __table_args__ = (
        UniqueConstraint("path", name="uq_literature_documents_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    suffix: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("literature_sources.id"), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    @classmethod
    def from_path(cls, path: Path) -> "LiteratureDocument":
        stat = path.stat()
        content: str | None = None
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md", ".tsv", ".csv"}:
            content = path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))

                if reader.is_encrypted:
                    reader.decrypt("")

                content = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception:
                content = None

        return cls(
            path=str(path.resolve()),
            filename=path.name,
            suffix=suffix,
            size_bytes=stat.st_size,
            content=content,
        )


class LiteratureSource(Base):
    __tablename__ = "literature_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="zotero")
    provider_item_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    citation_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(Text, nullable=False)
    creators_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    collections_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    zotero_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("literature_documents.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CandidateTermRecord(Base):
    __tablename__ = "candidate_terms"
    __table_args__ = (
        UniqueConstraint("document_id", "normalized_label", name="uq_candidate_terms_document_label"),
        UniqueConstraint("candidate_id", name="uq_candidate_terms_candidate_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("literature_documents.id"), nullable=False)
    extraction_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_runs.id"),
        nullable=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    synonyms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    proposed_parent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="new")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    curator_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    mappings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ols_matches_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    selected_ols_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ols_lookup_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_run")
    local_matches_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    selected_local_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_lookup_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_run")
    curator_decision: Mapped[str] = mapped_column(String(50), nullable=False, default="needs_review")
    refinement_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    permanently_rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
