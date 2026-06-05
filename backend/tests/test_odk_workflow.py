import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.github_export import GitHubExportResult
from backend.app.models.core import ReviewStatus
from backend.app.models.db import CandidateTermRecord, LiteratureDocument
from backend.app.odk.workflow import (
    CommandResult,
    OdkImplementationConfig,
    run_approved_candidate_workflow,
)


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'workflow.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    monkeypatch.setenv("OCA_ODK_AUDIT_LOG_PATH", str(tmp_path / "logs" / "audit.jsonl"))
    get_settings.cache_clear()
    db_session.Base.metadata.create_all(bind=engine)
    yield factory
    get_settings.cache_clear()


def config(tmp_path: Path, *, dry_run: bool) -> OdkImplementationConfig:
    ontology_path = tmp_path / "ppo" / "src" / "ontology"
    ontology_path.mkdir(parents=True)
    return OdkImplementationConfig(
        ontology_path=ontology_path,
        template_relative_path="templates/ai_approved_terms.tsv",
        validation_command="make test",
        audit_log_path=tmp_path / "logs" / "audit.jsonl",
        dry_run=dry_run,
        commit_message="Apply approved test candidates",
    )


def add_candidate(session, label: str, status: ReviewStatus) -> CandidateTermRecord:
    document = session.scalar(select(LiteratureDocument).where(LiteratureDocument.path == "__test__"))
    if document is None:
        document = LiteratureDocument(
            path="__test__",
            filename="test.txt",
            suffix=".txt",
            size_bytes=4,
            content="test",
        )
        session.add(document)
        session.flush()
    candidate = CandidateTermRecord(
        candidate_id=f"CAND:{label.replace(' ', '_')}",
        document_id=document.id,
        label=label,
        normalized_label=label,
        proposed_definition=f"Definition for {label}",
        synonyms_json="[]",
        proposed_parent="parent",
        confidence_score=0.8,
        review_status=status.value,
        evidence_json=json.dumps([{"quoted_text": f"Evidence for {label}"}]),
    )
    session.add(candidate)
    session.commit()
    return candidate


def test_dry_run_is_default_boundary_and_does_not_write_validate_or_upload(session_factory, tmp_path):
    with session_factory() as session:
        add_candidate(session, "accepted term", ReviewStatus.APPROVED)
        calls = {"validation": 0, "upload": 0}
        result = run_approved_candidate_workflow(
            session,
            config=config(tmp_path, dry_run=True),
            command_runner=lambda command, cwd: calls.__setitem__("validation", 1) or CommandResult(0),
            uploader=lambda files, message: calls.__setitem__("upload", 1)
            or GitHubExportResult(ok=True, message="uploaded"),
        )

    assert result.ok
    assert result.dry_run
    assert calls == {"validation": 0, "upload": 0}
    assert not (tmp_path / "ppo" / "src" / "ontology" / "templates" / "ai_approved_terms.tsv").exists()


def test_rejected_candidates_are_not_implemented(session_factory, tmp_path):
    with session_factory() as session:
        accepted = add_candidate(session, "accepted term", ReviewStatus.APPROVED)
        rejected = add_candidate(session, "rejected term", ReviewStatus.REJECTED)
        result = run_approved_candidate_workflow(
            session,
            config=config(tmp_path, dry_run=False),
            command_runner=lambda command, cwd: CommandResult(0, stdout="ok"),
            uploader=lambda files, message: GitHubExportResult(ok=True, message="uploaded", commit_url="url"),
        )
        session.refresh(accepted)
        session.refresh(rejected)

    template = (tmp_path / "ppo" / "src" / "ontology" / "templates" / "ai_approved_terms.tsv").read_text(
        encoding="utf-8"
    )
    assert result.ok
    assert "accepted term" in template
    assert "rejected term" not in template
    assert accepted.review_status == ReviewStatus.UPLOADED.value
    assert rejected.review_status == ReviewStatus.REJECTED.value


def test_validation_failure_blocks_upload_and_marks_candidates(session_factory, tmp_path):
    calls = {"uploaded": False}
    with session_factory() as session:
        candidate = add_candidate(session, "accepted term", ReviewStatus.APPROVED)
        result = run_approved_candidate_workflow(
            session,
            config=config(tmp_path, dry_run=False),
            command_runner=lambda command, cwd: CommandResult(2, stderr="robot failed"),
            uploader=lambda files, message: calls.__setitem__("uploaded", True)
            or GitHubExportResult(ok=True, message="uploaded"),
        )
        session.refresh(candidate)

    assert not result.ok
    assert "ODK validation failed" in result.message
    assert "robot failed" in result.message
    assert candidate.review_status == ReviewStatus.ODK_VALIDATION_FAILED.value
    assert calls["uploaded"] is False
    audit_text = (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert "validation_finished" in audit_text
    assert "upload_blocked" in audit_text


def test_validation_success_allows_upload_and_audits(session_factory, tmp_path):
    uploads = []
    with session_factory() as session:
        candidate = add_candidate(session, "accepted term", ReviewStatus.APPROVED_WITH_EDITS)
        result = run_approved_candidate_workflow(
            session,
            config=config(tmp_path, dry_run=False),
            command_runner=lambda command, cwd: CommandResult(0, stdout="validation ok"),
            uploader=lambda files, message: uploads.append((files, message))
            or GitHubExportResult(ok=True, message="uploaded", commit_url="https://example/commit"),
        )
        session.refresh(candidate)

    assert result.ok
    assert uploads
    assert candidate.review_status == ReviewStatus.UPLOADED.value
    assert result.upload.commit_url == "https://example/commit"
    audit_events = [
        json.loads(line)["event"]
        for line in (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert audit_events.index("validation_finished") < audit_events.index("upload_finished")
    assert "workflow_completed" in audit_events


def test_no_accepted_candidates_stops_before_implementation(session_factory, tmp_path):
    with session_factory() as session:
        add_candidate(session, "rejected term", ReviewStatus.REJECTED)
        result = run_approved_candidate_workflow(session, config=config(tmp_path, dry_run=False))

    assert not result.ok
    assert "No accepted candidates" in result.message
    assert not (tmp_path / "ppo" / "src" / "ontology" / "templates").exists()


def test_missing_suggestion_file_stops_odk_workflow_with_clear_error(session_factory, tmp_path):
    cfg = config(tmp_path, dry_run=True)
    cfg = OdkImplementationConfig(
        ontology_path=cfg.ontology_path,
        template_relative_path=cfg.template_relative_path,
        validation_command=cfg.validation_command,
        audit_log_path=cfg.audit_log_path,
        suggestion_file=tmp_path / "missing-suggestions.json",
        dry_run=True,
        commit_message=cfg.commit_message,
    )
    with session_factory() as session:
        add_candidate(session, "accepted term", ReviewStatus.APPROVED)
        result = run_approved_candidate_workflow(session, config=cfg)

    assert not result.ok
    assert "suggestion file was not found" in result.message
    assert result.suggestion_file == str(tmp_path / "missing-suggestions.json")
