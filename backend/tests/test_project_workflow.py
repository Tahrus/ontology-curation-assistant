import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "projects.sqlite3"
    monkeypatch.chdir(tmp_path)
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
    get_settings.cache_clear()
    db_session.ensure_runtime_schema()

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


def _create_project(client, tmp_path):
    response = client.post(
        "/api/projects",
        json={
            "name": "Protein precipitation",
            "ontology_id": "ppo",
            "ontology_title": "Protein Precipitation Ontology",
            "base_iri": "http://purl.obolibrary.org/obo/PPO_",
            "local_workspace_path": str(tmp_path),
            "github_url": "https://github.com/example/ppo",
            "zotero_literature_source_path": str(tmp_path / "zotero" / "storage"),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_project_creation_selection_and_literature_layout(client, tmp_path):
    project = _create_project(client, tmp_path)

    assert project["slug"] == "protein-precipitation"
    assert project["active"] is True
    assert (tmp_path / "projects" / project["slug"] / "literature" / "pdf").is_dir()
    assert (tmp_path / "projects" / project["slug"] / "curation" / "runs").is_dir()

    projects = client.get("/api/projects").json()
    assert projects["active_project"]["slug"] == project["slug"]
    assert projects["projects"][0]["paths"]["literature"].endswith("literature")

    selected = client.post(f"/api/projects/{project['slug']}/select", json={})
    assert selected.status_code == 200
    assert selected.json()["active"] is True
    alias = client.post(f"/api/projects/{project['slug']}/activate", json={})
    assert alias.status_code == 200
    assert alias.json()["active"] is True


def test_project_hierarchy_metadata_and_path_statuses(client, tmp_path):
    root = client.post(
        "/api/projects",
        json={
            "name": "Bioprocess Ontology",
            "ontology_id": "bpo",
            "ontology_title": "Bioprocess Ontology",
            "project_type": "upper_bioprocess_ontology",
            "description": "Upper-level ontology for bioprocess engineering.",
            "ontology_scope": ["bioprocess", "unit operation"],
            "ontology_namespace": "bpo",
            "base_iri": "http://purl.obolibrary.org/obo/BPO_",
            "local_workspace_path": str(tmp_path),
            "editable_ontology_path": str(tmp_path / "missing-edit.owl"),
            "built_ontology_path": str(tmp_path / "missing-release.owl"),
            "local_git_repository_path": str(tmp_path / "missing-git"),
            "minimal_scope_notes": "Broad bioprocess engineering root.",
        },
    )
    assert root.status_code == 200
    root_payload = root.json()
    assert root_payload["project_type"] == "upper_bioprocess_ontology"
    assert root_payload["ontology_scope"] == ["bioprocess", "unit operation"]
    assert root_payload["minimal_scope_notes"] == "Broad bioprocess engineering root."
    assert root_payload["path_statuses"]["editable_ontology_path"]["status"] == "missing"
    assert root_payload["path_statuses"]["local_git_repository_path"]["status"] == "missing"

    child = client.post(
        "/api/projects",
        json={
            "name": "Protein Precipitation Ontology",
            "ontology_id": "ppo",
            "ontology_title": "Protein Precipitation Ontology",
            "project_type": "domain_ontology",
            "parent_project_id": root_payload["id"],
            "description": "Domain ontology for protein precipitation.",
            "base_iri": "http://purl.obolibrary.org/obo/PPO_",
            "local_workspace_path": str(tmp_path),
        },
    )
    assert child.status_code == 200
    child_payload = child.json()
    assert child_payload["parent_project"]["ontology_id"] == "bpo"
    assert "dependency_projects" not in child_payload

    children = client.get(f"/api/projects/{root_payload['slug']}/children")
    assert children.status_code == 200
    assert children.json()[0]["ontology_id"] == "ppo"

    projects = client.get("/api/projects").json()
    reloaded_root = next(item for item in projects["projects"] if item["ontology_id"] == "bpo")
    assert reloaded_root["child_count"] == 1
    assert reloaded_root["children"][0]["ontology_id"] == "ppo"

    updated = client.patch(
        f"/api/projects/{child_payload['slug']}",
        json={
            "project_type": "existing_ontology_project",
            "minimal_scope_notes": "Existing ontology represented as a project node.",
            "local_workspace_path": str(tmp_path / "edited-workspace"),
            "local_git_repository_path": str(tmp_path / "prefer-repo"),
        },
    )
    assert updated.status_code == 200
    assert updated.json()["project_type"] == "existing_ontology_project"
    assert updated.json()["minimal_scope_notes"] == "Existing ontology represented as a project node."
    assert updated.json()["local_path"] == str(tmp_path / "edited-workspace")
    assert updated.json()["path_statuses"]["workspace_path"]["status"] == "ready"

    suggested = client.get("/api/projects/suggest-base-iri", params={"ontology_id": "PREFER"})
    assert suggested.status_code == 200
    assert suggested.json()["base_iri"] == "http://purl.obolibrary.org/obo/prefer.owl"


def test_project_metadata_validation(client, tmp_path):
    root = client.post(
        "/api/projects",
        json={
            "name": "Bioprocess Ontology",
            "ontology_id": "bpo",
            "project_type": "upper_bioprocess_ontology",
            "base_iri": "http://purl.obolibrary.org/obo/BPO_",
            "local_workspace_path": str(tmp_path),
        },
    )
    assert root.status_code == 200

    duplicate = client.post(
        "/api/projects",
        json={
            "name": "Duplicate BPO",
            "ontology_id": "BPO",
            "project_type": "domain_ontology",
            "local_workspace_path": str(tmp_path),
        },
    )
    assert duplicate.status_code == 409

    invalid_iri = client.post(
        "/api/projects",
        json={
            "name": "Bad IRI project",
            "ontology_id": "badiri",
            "project_type": "domain_ontology",
            "base_iri": "not an iri",
            "local_workspace_path": str(tmp_path),
        },
    )
    assert invalid_iri.status_code == 400

    child = client.post(
        "/api/projects",
        json={
            "name": "Protein Precipitation Ontology",
            "ontology_id": "ppo",
            "project_type": "domain_ontology",
            "parent_project_id": root.json()["id"],
            "local_workspace_path": str(tmp_path),
        },
    )
    assert child.status_code == 200

    self_parent = client.patch(
        f"/api/projects/{child.json()['slug']}",
        json={"parent_project_id": child.json()["id"]},
    )
    assert self_parent.status_code == 400

    circular = client.patch(
        f"/api/projects/{root.json()['slug']}",
        json={"parent_project_id": child.json()["id"]},
    )
    assert circular.status_code == 400


def test_curation_run_suggestion_review_evaluation_and_export(client, tmp_path):
    project = _create_project(client, tmp_path)
    raw_output = {
        "suggestions": [
            {
                "suggestion_type": "class",
                "label": "salt-induced precipitation",
                "definition": "A precipitation process induced by salt concentration.",
                "parent_class": "protein precipitation",
                "relations": [{"relation": "has input", "target": "salt", "justification": "stated"}],
                "synonyms": ["salting-out precipitation"],
                "evidence": [
                    {
                        "source": "paper-1.md",
                        "document_title": "Example paper",
                        "quote_or_span": "Proteins precipitated after salt addition.",
                        "section": "Results",
                        "reason": "Supports the process label.",
                    }
                ],
                "duplicate_check": {"possible_duplicate": False},
                "confidence": "high",
            },
            {
                "suggestion_type": "class",
                "label": "unsupported candidate",
                "confidence": "low",
            },
        ]
    }
    run = client.post(
        "/api/curation/runs",
        json={
            "strategy": "literature_plus_ontology",
            "name": "first run",
            "model": "mock-model",
            "raw_output": json.dumps(raw_output),
        },
    )
    assert run.status_code == 200
    assert run.json()["parsed_suggestions"] == 2

    suggestions = client.get("/api/suggestions").json()
    assert len(suggestions) == 2
    accepted = next(item for item in suggestions if item["label"] == "salt-induced precipitation")
    unsupported = next(item for item in suggestions if item["label"] == "unsupported candidate")

    accepted_review = client.post(
        f"/api/suggestions/{accepted['id']}/review",
        json={"status": "edited", "edited_label": "salt-induced protein precipitation", "review_time_seconds": 30},
    )
    assert accepted_review.status_code == 200
    rejected_review = client.post(
        f"/api/suggestions/{unsupported['id']}/review",
        json={"status": "unsupported", "comment": "No evidence span."},
    )
    assert rejected_review.status_code == 200

    metrics = client.post("/api/evaluation/compute").json()["metrics"]
    assert metrics["total_suggestions"] == 2
    assert metrics["total_reviewed"] == 2
    assert metrics["edited"] == 1
    assert metrics["unsupported"] == 1
    assert metrics["unsupported_rate"] == 0.5
    assert metrics["evidence_traceability"] == 0.5

    export = client.get(f"/api/projects/{project['slug']}/exports/accepted.robot.tsv")
    assert export.status_code == 200
    assert "salt-induced protein precipitation" in export.text
    assert "unsupported candidate" not in export.text


def test_run_comparison_and_odk_logging(client, tmp_path):
    project = _create_project(client, tmp_path)
    first = client.post(
        "/api/curation/runs",
        json={
            "strategy": "literature_only",
            "raw_output": json.dumps({"suggestions": [{"label": "Alpha", "suggestion_type": "class"}]}),
        },
    ).json()
    second = client.post(
        "/api/curation/runs",
        json={
            "strategy": "ontology_only",
            "raw_output": json.dumps({"suggestions": [{"label": "alpha", "suggestion_type": "class"}]}),
        },
    ).json()

    comparison = client.post(
        "/api/evaluation/compare",
        json={"first_run_id": first["id"], "second_run_id": second["id"]},
    )
    assert comparison.status_code == 200
    assert comparison.json()["exact_label_overlap"] == 0
    assert comparison.json()["normalized_label_overlap"] == 1

    validate = client.get(f"/api/projects/{project['slug']}/odk/validate")
    assert validate.status_code == 200
    assert validate.json()["status"] in {"ok", "warning"}

    logs = client.get(f"/api/projects/{project['slug']}/odk/logs")
    assert logs.status_code == 200
    assert logs.json()[0]["operation"] == "validate"
