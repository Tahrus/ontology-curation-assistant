import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from backend.app.cli import app
from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.extraction.parser import CandidateExtractionParseError, parse_candidate_response
from backend.app.extraction.prompts import build_candidate_extraction_prompt
from backend.app.models.db import CandidateTermRecord, LiteratureDocument


runner = CliRunner()


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", session_factory)
    monkeypatch.delenv("OCA_LLM_PROVIDER", raising=False)
    get_settings.cache_clear()

    db_session.Base.metadata.create_all(bind=engine)
    yield session_factory
    get_settings.cache_clear()


def insert_document(session_factory, tmp_path: Path, content: str) -> int:
    source_path = tmp_path / "source.txt"
    source_path.write_text(content, encoding="utf-8")
    with session_factory() as session:
        document = LiteratureDocument.from_path(source_path)
        session.add(document)
        session.commit()
        return document.id


def write_mock_output(tmp_path: Path) -> Path:
    mock_output = tmp_path / "mock_llm_output.json"
    mock_output.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "label": "preferential hydration",
                        "proposed_definition": (
                            "Preferential exclusion of cosolvent from the protein domain."
                        ),
                        "synonyms": ["water of preferential hydration"],
                        "proposed_parent": "protein-solvent interaction",
                        "confidence_score": 0.92,
                        "evidence": [
                            {
                                "quoted_text": (
                                    "There is no direct relation between water of "
                                    "preferential hydration and water of hydration."
                                ),
                                "section_title": None,
                                "page_number": None,
                                "char_start": None,
                                "char_end": None,
                                "direct_or_inferred": "direct",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return mock_output


def test_prompt_generation_contains_curation_rules() -> None:
    prompt = build_candidate_extraction_prompt(
        "Preferential hydration stabilizes proteins in solution.",
        document_id=1,
        filename="paper.txt",
    )

    assert "ontology curators" in prompt
    assert "Return only valid JSON" in prompt
    assert "author names" in prompt
    assert "affiliations/institutions" in prompt
    assert "download headers" in prompt
    assert "Preferential hydration stabilizes proteins" in prompt


def test_extract_candidates_prompt_out_does_not_persist(isolated_db, tmp_path):
    document_id = insert_document(
        isolated_db,
        tmp_path,
        "Preferential hydration stabilizes proteins in solution.",
    )
    prompt_path = tmp_path / "candidate_prompt.txt"

    result = runner.invoke(
        app,
        ["extract-candidates", str(document_id), "--prompt-out", str(prompt_path)],
    )

    assert result.exit_code == 0
    assert prompt_path.exists()
    assert "Return only valid JSON" in prompt_path.read_text(encoding="utf-8")
    with isolated_db() as session:
        count = len(session.scalars(select(CandidateTermRecord)).all())
    assert count == 0


def test_extract_candidates_without_provider_fails_clearly(isolated_db, tmp_path):
    document_id = insert_document(isolated_db, tmp_path, "A source document.")

    result = runner.invoke(app, ["extract-candidates", str(document_id)])

    assert result.exit_code != 0
    assert "No LLM provider configured" in result.output
    assert "regex" not in result.output.lower()


def test_mock_extraction_persists_candidate(isolated_db, tmp_path):
    document_id = insert_document(isolated_db, tmp_path, "Preferential hydration source text.")
    mock_output = write_mock_output(tmp_path)

    result = runner.invoke(
        app,
        ["extract-candidates", str(document_id), "--mock-output", str(mock_output)],
    )

    assert result.exit_code == 0
    assert "Inserted:" in result.output
    with isolated_db() as session:
        candidate = session.scalar(select(CandidateTermRecord))
    assert candidate is not None
    assert candidate.label == "preferential hydration"


def test_mock_extraction_dry_run_does_not_persist(isolated_db, tmp_path):
    document_id = insert_document(isolated_db, tmp_path, "Preferential hydration source text.")
    mock_output = write_mock_output(tmp_path)

    result = runner.invoke(
        app,
        [
            "extract-candidates",
            str(document_id),
            "--mock-output",
            str(mock_output),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "preferential hydration" in result.output
    assert "Dry run" in result.output
    with isolated_db() as session:
        count = len(session.scalars(select(CandidateTermRecord)).all())
    assert count == 0


def test_validation_failure_invalid_direct_or_inferred() -> None:
    raw = json.dumps(
        {
            "candidates": [
                {
                    "label": "preferential hydration",
                    "confidence_score": 0.9,
                    "evidence": [
                        {
                            "quoted_text": "An exact quote.",
                            "direct_or_inferred": "unsupported",
                        }
                    ],
                }
            ]
        }
    )

    with pytest.raises(CandidateExtractionParseError, match="direct_or_inferred"):
        parse_candidate_response(raw)


def test_validation_failure_missing_evidence() -> None:
    raw = json.dumps(
        {
            "candidates": [
                {
                    "label": "preferential hydration",
                    "confidence_score": 0.9,
                    "evidence": [],
                }
            ]
        }
    )

    with pytest.raises(CandidateExtractionParseError, match="evidence"):
        parse_candidate_response(raw)


def test_duplicate_mock_extraction_skips_candidate(isolated_db, tmp_path):
    document_id = insert_document(isolated_db, tmp_path, "Preferential hydration source text.")
    mock_output = write_mock_output(tmp_path)

    first = runner.invoke(
        app,
        ["extract-candidates", str(document_id), "--mock-output", str(mock_output)],
    )
    second = runner.invoke(
        app,
        ["extract-candidates", str(document_id), "--mock-output", str(mock_output)],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Skipped:" in second.output
    with isolated_db() as session:
        candidates = session.scalars(select(CandidateTermRecord)).all()
    assert len(candidates) == 1


def test_candidates_list_empty_database(isolated_db):
    result = runner.invoke(app, ["candidates-list"])

    assert result.exit_code == 0
    assert "No candidate terms found" in result.output


def test_candidate_show_and_missing_candidate(isolated_db, tmp_path):
    document_id = insert_document(isolated_db, tmp_path, "Preferential hydration source text.")
    mock_output = write_mock_output(tmp_path)
    extract_result = runner.invoke(
        app,
        ["extract-candidates", str(document_id), "--mock-output", str(mock_output)],
    )
    assert extract_result.exit_code == 0

    with isolated_db() as session:
        candidate = session.scalar(select(CandidateTermRecord))

    show_result = runner.invoke(app, ["candidate-show", str(candidate.id)])
    missing_result = runner.invoke(app, ["candidate-show", "999999"])

    assert show_result.exit_code == 0
    assert "preferential hydration" in show_result.output
    assert "water of preferential hydration" in show_result.output
    assert missing_result.exit_code != 0
    assert "No candidate term found" in missing_result.output
