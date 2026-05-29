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
        document_columns = {
            column["name"] for column in inspector.get_columns("literature_documents")
        }
        if "source_id" not in document_columns:
            connection.execute(text("ALTER TABLE literature_documents ADD COLUMN source_id INTEGER"))

        if "literature_sources" not in inspector.get_table_names():
            return

        source_columns = {
            column["name"] for column in inspector.get_columns("literature_sources")
        }
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
            "refinement_guidance": "TEXT",
            "rejection_reason": "TEXT",
            "permanently_rejected_at": "DATETIME",
        }
        for column_name, definition in candidate_additions.items():
            if column_name not in candidate_columns:
                connection.execute(
                    text(f"ALTER TABLE candidate_terms ADD COLUMN {column_name} {definition}")
                )
