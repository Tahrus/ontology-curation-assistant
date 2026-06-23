from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.main import app
from backend.app.cli import app as cli_app

from backend.app.literature.canonical import (
    RepositoryPaths,
    build_combined,
    clean_llm_markdown,
    list_entries,
    normalize_doi,
    normalize_pii,
    reset_repository,
    upsert_markdown,
)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'canonical.sqlite3'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    get_settings.cache_clear()
    db_session.ensure_runtime_schema()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_identifier_normalization() -> None:
    assert {normalize_pii(value) for value in ("S0098-1354(25)00197-8", "S0098135425001978", "s0098 1354(25)00197 8")} == {"S0098135425001978"}
    assert {normalize_doi(value) for value in ("https://doi.org/10.1016/j.compchemeng.2025.109193", "doi:10.1016/j.compchemeng.2025.109193", "10.1016/J.COMPCHEMENG.2025.109193")} == {"10.1016/j.compchemeng.2025.109193"}


def test_markdown_header_is_minimal_and_identifiers_are_not_duplicated() -> None:
    output = clean_llm_markdown("---\na: b\n---\n# Old title\nPII: `S0098135425001978`\nPII: S0098-1354(25)00197-8\n## Abstract\nUseful text", title="Dynamics of batch protein precipitation", pii="S0098-1354(25)00197-8", doi="https://doi.org/10.1016/j.compchemeng.2025.109193")
    assert output.startswith("# Dynamics of batch protein precipitation\n\nPII: `S0098135425001978`\nDOI: `10.1016/j.compchemeng.2025.109193`")
    assert output.count("PII:") == 1
    assert output.count("DOI:") == 1
    assert not output.startswith("---")


def test_doi_then_pii_reuses_entry_and_preserves_curation(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    first, duplicate = upsert_markdown(paths, title="Dynamics of batch protein precipitation", markdown="## Abstract\nFirst extraction", doi="10.1016/j.compchemeng.2025.109193")
    assert not duplicate
    metadata_path = paths.metadata / f"{first['canonical_id']}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(project_tags=["ppo"], review_status="accepted", annotations={"note": "keep"})
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    second, duplicate = upsert_markdown(paths, title="Dynamics of batch protein precipitation", markdown="## Abstract\nMore complete extraction with useful results", pii="S0098-1354(25)00197-8")
    assert duplicate
    assert second["canonical_id"] == "S0098135425001978"
    assert second["doi"] == "10.1016/j.compchemeng.2025.109193"
    assert second["project_tags"] == ["ppo"]
    assert second["review_status"] == "accepted"
    assert second["annotations"] == {"note": "keep"}
    assert len(list_entries(paths)) == 1


def test_combined_contains_each_canonical_paper_once(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    upsert_markdown(paths, title="Paper one canonical title", markdown="## Abstract\nOne", doi="10.1000/one")
    upsert_markdown(paths, title="Paper one canonical title", markdown="## Abstract\nOne expanded", pii="S0098135425001978")
    upsert_markdown(paths, title="Paper two canonical title", markdown="## Abstract\nTwo", doi="10.1000/two")
    assert build_combined(paths) == 2
    combined = paths.combined.read_text(encoding="utf-8")
    assert combined.count("# Paper one canonical title") == 1
    assert combined.count("# Paper two canonical title") == 1


def test_reset_affects_only_selected_project(tmp_path: Path) -> None:
    first = RepositoryPaths.from_root(tmp_path / "projects" / "one" / "literature")
    second = RepositoryPaths.from_root(tmp_path / "projects" / "two" / "literature")
    upsert_markdown(first, title="First project paper title", markdown="text", doi="10.1000/one")
    upsert_markdown(second, title="Second project paper title", markdown="text", doi="10.1000/two")
    reset_repository(first)
    assert list_entries(first) == []
    assert len(list_entries(second)) == 1


def test_project_scoped_import_api(client, tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    (source / "paper.md").write_text("# API imported paper title\n\nPII: S0098-1354(25)00197-8\nDOI: 10.1016/j.compchemeng.2025.109193\n\n## Abstract\nUseful.", encoding="utf-8")
    created = client.post("/api/projects", json={"name": "Literature API", "ontology_id": "litapi", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": True})
    assert created.status_code == 200, created.text
    imported = client.post("/api/literature/import", json={"project": created.json()["slug"], "pdf_dir": str(source)})
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 1
    listing = client.get(f"/api/literature/canonical?project={created.json()['slug']}")
    assert listing.status_code == 200
    assert listing.json()["entries"][0]["pii"] == "S0098135425001978"


def test_project_scoped_import_cli(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input"
    source.mkdir()
    (source / "paper.md").write_text("# CLI imported canonical paper\n\nDOI: 10.1000/cli\n\n## Abstract\nUseful.", encoding="utf-8")
    paths = RepositoryPaths.from_root(tmp_path / "projects" / "cli" / "literature")
    fake_session = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr("backend.app.cli._literature_project_paths", lambda project: (fake_session, SimpleNamespace(slug=project), paths))
    result = CliRunner().invoke(cli_app, ["literature", "import", "--project", "cli", "--pdf-dir", str(source)])
    assert result.exit_code == 0, result.output
    assert "imported 1" in result.output
    assert len(list_entries(paths)) == 1
