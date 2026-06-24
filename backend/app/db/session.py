from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def ensure_runtime_schema() -> None:
    """Apply tiny SQLite-compatible schema additions until migrations exist."""
    from backend.app.models import db as _models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "literature_documents" not in inspector.get_table_names():
        return

    with engine.begin() as connection:
        if "projects" in inspector.get_table_names():
            project_columns = {
                column["name"] for column in inspector.get_columns("projects")
            }
            project_additions = {
                "project_type": "VARCHAR(80) DEFAULT 'domain_ontology'",
                "parent_project_id": "INTEGER",
                "ontology_scope": "TEXT",
                "minimal_scope_notes": "TEXT",
                "ontology_namespace": "VARCHAR(64)",
                "dependency_projects_json": "TEXT DEFAULT '[]' NOT NULL",
                "external_references_json": "TEXT DEFAULT '[]' NOT NULL",
                "editable_ontology_path": "VARCHAR(1024)",
                "built_ontology_path": "VARCHAR(1024)",
                "literature_repository_path": "VARCHAR(1024)",
                "local_git_repository_path": "VARCHAR(1024)",
            }
            for column_name, definition in project_additions.items():
                if column_name not in project_columns:
                    connection.execute(
                        text(f"ALTER TABLE projects ADD COLUMN {column_name} {definition}")
                    )

        document_columns = {
            column["name"] for column in inspector.get_columns("literature_documents")
        }
        document_additions = {
            "project_id": "INTEGER",
            "title": "TEXT",
            "authors_json": "TEXT",
            "year": "VARCHAR(20)",
            "doi": "VARCHAR(255)",
            "source_pdf_path": "VARCHAR(1024)",
            "markdown_path": "VARCHAR(1024)",
            "extraction_status": "VARCHAR(50)",
            "content_hash": "VARCHAR(128)",
            "duplicate_group_id": "VARCHAR(128)",
        }
        for column_name, definition in document_additions.items():
            if column_name not in document_columns:
                connection.execute(
                    text(f"ALTER TABLE literature_documents ADD COLUMN {column_name} {definition}")
                )
        if "source_id" not in document_columns:
            connection.execute(text("ALTER TABLE literature_documents ADD COLUMN source_id INTEGER"))

        if "literature_sources" not in inspector.get_table_names():
            return

        source_columns = {
            column["name"] for column in inspector.get_columns("literature_sources")
        }
        source_additions = {
            "project_id": "INTEGER",
            "source_type": "VARCHAR(50)",
            "source_path": "VARCHAR(1024)",
            "status": "VARCHAR(50)",
            "last_imported_at": "DATETIME",
            "project_tags_json": "TEXT",
            "identifiers_json": "TEXT",
        }
        for column_name, definition in source_additions.items():
            if column_name not in source_columns:
                connection.execute(
                    text(f"ALTER TABLE literature_sources ADD COLUMN {column_name} {definition}")
                )
        if "zotero_version" not in source_columns:
            connection.execute(text("ALTER TABLE literature_sources ADD COLUMN zotero_version INTEGER"))
        if "item_type" not in source_columns:
            connection.execute(text("ALTER TABLE literature_sources ADD COLUMN item_type VARCHAR(100)"))
        if "synced_at" not in source_columns:
            connection.execute(text("ALTER TABLE literature_sources ADD COLUMN synced_at DATETIME"))

        if "candidate_terms" not in inspector.get_table_names():
            return

        candidate_columns = {
            column["name"] for column in inspector.get_columns("candidate_terms")
        }
        candidate_additions = {
            "project_id": "INTEGER",
            "curator_rationale": "TEXT",
            "source_evidence": "TEXT",
            "mappings_json": "TEXT DEFAULT '[]' NOT NULL",
            "ols_matches_json": "TEXT DEFAULT '[]' NOT NULL",
            "selected_ols_json": "TEXT",
            "ols_lookup_status": "VARCHAR(50) DEFAULT 'not_run' NOT NULL",
            "local_matches_json": "TEXT DEFAULT '[]' NOT NULL",
            "selected_local_json": "TEXT",
            "local_lookup_status": "VARCHAR(50) DEFAULT 'not_run' NOT NULL",
            "curator_decision": "VARCHAR(50) DEFAULT 'needs_review' NOT NULL",
            "graph_review_json": "TEXT DEFAULT '{}' NOT NULL",
            "refinement_guidance": "TEXT",
            "rejection_reason": "TEXT",
            "permanently_rejected_at": "DATETIME",
        }
        for column_name, definition in candidate_additions.items():
            if column_name not in candidate_columns:
                connection.execute(
                    text(f"ALTER TABLE candidate_terms ADD COLUMN {column_name} {definition}")
                )

        if "extraction_runs" in inspector.get_table_names():
            extraction_columns = {
                column["name"] for column in inspector.get_columns("extraction_runs")
            }
            if "project_id" not in extraction_columns:
                connection.execute(text("ALTER TABLE extraction_runs ADD COLUMN project_id INTEGER"))

        if "literature_index" in inspector.get_table_names():
            index_columns = {
                column["name"] for column in inspector.get_columns("literature_index")
            }
            if "project_id" not in index_columns:
                connection.execute(text("ALTER TABLE literature_index ADD COLUMN project_id INTEGER"))
