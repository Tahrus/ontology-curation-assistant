from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class LiteratureDocument(Base):
    __tablename__ = "literature_documents"
    __table_args__ = (
        UniqueConstraint("path", name="uq_literature_documents_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    suffix: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("literature_sources.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    markdown_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extraction_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duplicate_group_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="zotero")
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_item_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    citation_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(Text, nullable=False)
    creators_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    identifiers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
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
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
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
    graph_review_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
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


class LiteratureIndexEntry(Base):
    __tablename__ = "literature_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("literature_documents.id"), nullable=True)
    paper_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    section_heading: Mapped[str] = mapped_column(String(255), nullable=False)
    subsection_heading: Mapped[str | None] = mapped_column(String(255), nullable=True)
    passage_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zotero_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_terms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_projects_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ontology_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ontology_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_type: Mapped[str] = mapped_column(String(80), nullable=False, default="domain_ontology")
    parent_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    ontology_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    minimal_scope_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ontology_namespace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dependency_projects_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    external_references_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    base_iri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    term_id_prefix: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    odk_repo_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    editable_ontology_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    built_ontology_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    literature_repository_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_git_repository_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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


class CurationRun(Base):
    __tablename__ = "curation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_strategy: Mapped[str] = mapped_column(String(80), nullable=False)
    context_configuration_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    literature_snapshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ontology_snapshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    curation_run_id: Mapped[int] = mapped_column(ForeignKey("curation_runs.id"), nullable=False, index=True)
    suggestion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    relations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    synonyms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    duplicate_check_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    confidence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_llm_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("suggestions.id"), nullable=False, index=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    edited_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edited_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_parent_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edited_relation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edited_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relation_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class EvaluationMetric(Base):
    __tablename__ = "evaluation_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    curation_run_id: Mapped[int | None] = mapped_column(ForeignKey("curation_runs.id"), nullable=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class OdkOperationLog(Base):
    __tablename__ = "odk_operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    working_directory: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="logged")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
