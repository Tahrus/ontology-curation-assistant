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
from backend.app.models.db import AppSetting

from backend.app.literature.canonical import (
    RepositoryPaths,
    build_combined,
    clean_llm_markdown,
    cleanup_unpromoted_staged,
    import_directory,
    list_curated_entries,
    list_entries,
    normalize_doi,
    normalize_pii,
    promote_staged_entry,
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
    first, _ = upsert_markdown(paths, title="Paper one canonical title", markdown="## Abstract\nOne", doi="10.1000/one")
    upsert_markdown(paths, title="Paper one canonical title", markdown="## Abstract\nOne expanded", pii="S0098135425001978")
    second, _ = upsert_markdown(paths, title="Paper two canonical title", markdown="## Abstract\nTwo", doi="10.1000/two")
    promote_staged_entry(paths, "S0098135425001978", project_tags=["project-one"])
    promote_staged_entry(paths, second["canonical_id"], project_tags=["project-two"])
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
    assert listing.json()["entries"] == []
    assert listing.json()["staged_entries"][0]["pii"] == "S0098135425001978"


def test_api_promotion_later_tags_and_cleanup_are_safe(client, tmp_path: Path) -> None:
    source = tmp_path / "review-input"
    source.mkdir()
    (source / "promote.md").write_text("# Promote this staged paper\n\nDOI: 10.1000/promote\n\nText", encoding="utf-8")
    (source / "discard.md").write_text("# Discard this staged paper\n\nDOI: 10.1000/discard\n\nText", encoding="utf-8")
    project = client.post("/api/projects", json={"name": "Review project", "ontology_id": "review", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": True}).json()
    assert client.post("/api/literature/import", json={"project": project["slug"], "pdf_dir": str(source)}).status_code == 200
    repository = client.get(f"/api/literature/canonical?project={project['slug']}").json()
    promote_id = next(item["id"] for item in repository["staged_entries"] if item["doi"] == "10.1000/promote")
    before = client.post("/api/extraction/candidates", json={"dry_run": True})
    assert before.status_code == 200
    assert before.json()["would_extract"] is False
    promoted = client.post(f"/api/literature/staged/{promote_id}/promote", json={"project": project["slug"], "project_tags": [project["slug"], project["slug"]]})
    assert promoted.status_code == 200, promoted.text
    after = client.post("/api/extraction/candidates", json={"dry_run": True})
    assert after.status_code == 200
    assert after.json()["would_extract"] is True
    later_project = client.post("/api/projects", json={"name": "Later project", "ontology_id": "later", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": False}).json()
    edited = client.patch(f"/api/literature/curated/{promote_id}", json={"project": project["slug"], "project_tags": [project["slug"], later_project["slug"], later_project["slug"]]})
    assert edited.status_code == 200
    assert edited.json()["project_tags"] == [project["slug"], later_project["slug"]]
    refused = client.post("/api/literature/cleanup-staged", json={"project": project["slug"], "confirm": False})
    assert refused.status_code == 400
    cleanup = client.post("/api/literature/cleanup-staged", json={"project": project["slug"], "confirm": True})
    assert cleanup.status_code == 200
    assert cleanup.json()["deleted_count"] == 1
    final = client.get(f"/api/literature/canonical?project={project['slug']}").json()
    assert len(final["curated_entries"]) == 1
    assert final["curated_entries"][0]["project_tags"] == [project["slug"], later_project["slug"]]


def test_api_cleanup_includes_legacy_global_managed_artifacts(client, tmp_path: Path) -> None:
    project = client.post(
        "/api/projects",
        json={"name": "Legacy cleanup", "ontology_id": "legacy-cleanup", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": True},
    ).json()
    legacy_root = tmp_path / "literature"
    leftovers = []
    for folder, filename in (("raw", "raw.md"), ("context", "context.md"), ("papers", "paper.md"), ("reports", "report.json")):
        path = legacy_root / folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated", encoding="utf-8")
        leftovers.append(path)
    (legacy_root / "metadata").mkdir(parents=True)
    aggregate = legacy_root / "metadata" / "literature_index.json"
    aggregate.write_text(json.dumps({"papers": []}), encoding="utf-8")
    leftovers.append(aggregate)
    original = tmp_path / "Zotero" / "storage" / "ITEMKEY" / "paper.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"external Zotero original")

    preview = client.post("/api/literature/cleanup-staged", json={"project": project["slug"], "dry_run": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["files_deleted_count"] == 5
    assert len(preview.json()["repositories"]) == 2
    assert all(path.exists() for path in leftovers)

    cleanup = client.post("/api/literature/cleanup-staged", json={"project": project["slug"], "confirm": True})
    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["orphan_files_deleted_count"] == 5
    assert all(not path.exists() for path in leftovers)
    assert original.exists()


def test_publisher_settings_are_masked_and_environment_wins(client, monkeypatch) -> None:
    saved = client.post("/api/config/publisher", json={"elsevier_api_key": "stored-secret", "elsevier_inst_token": "stored-token", "publisher_api_enrichment_enabled": True})
    assert saved.status_code == 200
    assert "stored-secret" not in saved.text
    assert "stored-token" not in saved.text
    monkeypatch.setenv("ELSEVIER_API_KEY", "environment-secret")
    get_settings.cache_clear()
    status = client.get("/api/config/status")
    assert status.status_code == 200
    assert status.json()["publisher"]["api_key"] == "configured"
    assert status.json()["publisher"]["api_key_source"] == "environment"
    assert "environment-secret" not in status.text
    assert "stored-secret" not in status.text


def test_publisher_settings_have_non_null_defaults_without_saved_rows(client) -> None:
    response = client.get("/api/config/status")
    assert response.status_code == 200
    publisher = response.json()["publisher"]
    assert publisher is not None
    assert publisher["enable_publisher_api_enrichment"] is False
    assert publisher["elsevier_api_key"] == ""
    assert publisher["elsevier_inst_token"] == ""
    assert publisher["elsevier_api_base_url"] == "https://api.elsevier.com"


def test_publisher_settings_backfill_partial_config_and_preserve_unrelated_settings(client) -> None:
    assert client.post("/api/config", json={"key": "unrelated_setting", "value": "keep-me"}).status_code == 200
    assert client.post("/api/config", json={"key": "publisher_api_enrichment_enabled", "value": "true"}).status_code == 200
    publisher = client.get("/api/config/status").json()["publisher"]
    assert publisher["enable_publisher_api_enrichment"] is True
    assert publisher["elsevier_api_key"] == ""
    assert publisher["elsevier_api_base_url"] == "https://api.elsevier.com"

    saved = client.post("/api/config/publisher", json={"elsevier_api_key": "new-secret"})
    assert saved.status_code == 200
    assert "new-secret" not in saved.text
    with db_session.SessionLocal() as session:
        assert session.get(AppSetting, "unrelated_setting").value == "keep-me"
        assert session.get(AppSetting, "elsevier_api_key").value == "new-secret"


def test_publisher_settings_allow_clearing_secrets(client) -> None:
    assert client.post("/api/config/publisher", json={"elsevier_api_key": "temporary-secret"}).status_code == 200
    cleared = client.post("/api/config/publisher", json={"elsevier_api_key": "", "elsevier_inst_token": ""})
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False
    with db_session.SessionLocal() as session:
        assert session.get(AppSetting, "elsevier_api_key").value == ""


def test_promote_preserves_reviewed_content_tags_and_traceability(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    staged, _ = upsert_markdown(paths, title="Staged paper title", markdown="## Abstract\nPipeline text", doi="10.1000/staged")
    curated = promote_staged_entry(
        paths,
        staged["canonical_id"],
        metadata={"title": "Reviewed paper title", "journal": "Reviewed Journal"},
        markdown="## Abstract\nHuman reviewed text",
        project_tags=["ppo", "ppo", "new-project"],
    )
    assert curated["title"] == "Reviewed paper title"
    assert curated["project_tags"] == ["ppo", "new-project"]
    assert curated["staged_entry_id"] == staged["canonical_id"]
    assert "Human reviewed text" in Path(curated["markdown_file"]).read_text(encoding="utf-8")
    assert len(list_curated_entries(paths)) == 1
    assert list_entries(paths)[0]["promoted_literature_id"] == staged["canonical_id"]


def test_cleanup_deletes_only_unpromoted_staged_entries(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    promoted, _ = upsert_markdown(paths, title="Promoted staged paper", markdown="text", doi="10.1000/promoted")
    unpromoted, _ = upsert_markdown(paths, title="Unpromoted staged paper", markdown="text", doi="10.1000/unpromoted")
    promote_staged_entry(paths, promoted["canonical_id"], project_tags=["ppo"])
    result = cleanup_unpromoted_staged(paths)
    assert result["deleted_ids"] == [unpromoted["canonical_id"]]
    assert len(list_curated_entries(paths)) == 1
    assert list_curated_entries(paths)[0]["project_tags"] == ["ppo"]
    assert len(list_entries(paths)) == 1


def test_import_registers_repository_relative_staged_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "external-zotero"
    source.mkdir()
    external = source / "paper.md"
    external.write_text("# Artifact tracked paper\n\nDOI: 10.1000/artifacts\n\nText", encoding="utf-8")
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    result = import_directory(paths, source, source_type="zotero_storage")
    assert result.imported == 1
    entry = list_entries(paths)[0]
    assert entry["repository_stage"] == "staged"
    assert list_curated_entries(paths) == []
    artifacts = {item["artifact_type"]: item for item in entry["artifacts"]}
    assert {"metadata_json", "paper_markdown", "source_copy"} <= set(artifacts)
    assert all(not Path(item["path"]).is_absolute() for item in artifacts.values())
    assert all(item["ownership"] == "staged" for item in artifacts.values())
    assert external.exists()


def test_cleanup_removes_legacy_generated_artifacts_orphans_and_empty_dirs(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    staged, _ = upsert_markdown(paths, title="Uncurated artifact paper", markdown="Text", doi="10.1000/uncurated")
    for folder, filename in (("raw", "raw.md"), ("context", "context.md"), ("papers", "paper.md"), ("reports", "report.json")):
        target = paths.root / folder / "nested" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated", encoding="utf-8")
    paths.combined.write_text("staged combined output", encoding="utf-8")
    external = tmp_path / "Zotero" / "storage" / "original.pdf"
    external.parent.mkdir(parents=True)
    external.write_bytes(b"external")
    preview = cleanup_unpromoted_staged(paths, dry_run=True)
    assert preview["dry_run"] is True
    assert preview["orphan_files_deleted_count"] == 4
    assert external.exists()
    assert (paths.metadata / f"{staged['canonical_id']}.json").exists()
    result = cleanup_unpromoted_staged(paths)
    assert result["deleted_ids"] == [staged["canonical_id"]]
    assert result["orphan_files_deleted_count"] == 4
    assert result["files_deleted_count"] >= 7
    assert result["combined_removed"] is True
    assert result["errors"] == []
    assert not paths.combined.exists()
    assert not (paths.root / "raw").exists()
    assert not (paths.root / "context").exists()
    assert not (paths.root / "papers").exists()
    assert not (paths.root / "reports").exists()
    assert external.exists()


def test_cleanup_preserves_curated_artifacts_and_rebuilds_combined(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    promoted, _ = upsert_markdown(paths, title="Curated protected paper", markdown="## Abstract\nCurated evidence", doi="10.1000/curated")
    unpromoted, _ = upsert_markdown(paths, title="Delete staged paper", markdown="Staged only", doi="10.1000/delete")
    curated = promote_staged_entry(paths, promoted["canonical_id"], project_tags=["ppo"])
    paths.combined.write_text("stale staged combined content", encoding="utf-8")
    result = cleanup_unpromoted_staged(paths)
    assert unpromoted["canonical_id"] in result["deleted_ids"]
    assert result["curated_count"] == 1
    assert Path(curated["metadata_file"]).exists()
    assert Path(curated["markdown_file"]).exists()
    assert promoted["canonical_id"] in paths.combined.read_text(encoding="utf-8") or "Curated protected paper" in paths.combined.read_text(encoding="utf-8")
    assert "stale staged combined content" not in paths.combined.read_text(encoding="utf-8")


def test_existing_single_stage_data_is_non_destructively_marked_for_review(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    paths.ensure()
    legacy_metadata = {"canonical_id": "legacy-paper", "title": "Existing literature paper", "review_status": "accepted"}
    metadata_path = paths.metadata / "legacy-paper.json"
    markdown_path = paths.markdown / "legacy-paper.md"
    metadata_path.write_text(json.dumps(legacy_metadata), encoding="utf-8")
    markdown_path.write_text("# Existing literature paper\n\nText", encoding="utf-8")
    entries = list_entries(paths)
    assert entries[0]["repository_stage"] == "staged"
    assert entries[0]["curation_status"] == "needs_review"
    assert entries[0]["review_status"] == "accepted"
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == legacy_metadata
    assert markdown_path.read_text(encoding="utf-8").endswith("Text")
    assert list_curated_entries(paths) == []


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
