import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.main import app
from backend.app.models.db import AppSetting, CandidateTermRecord, LiteratureDocument, LiteratureSource
from backend.app.ontology.local import index_ontology_file, scan_ontology_folder
from backend.app.ontology.ols import OlsLookupService, parse_ols_search_response


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "api.sqlite3"
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


def test_root_serves_browser_ui(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Ontology Curation Assistant" in response.text
    assert 'id="candidate-list"' in response.text
    assert "Dashboard" in response.text
    assert "theme-light" in response.text
    assert "Meta-Ontology Graph" in response.text
    assert "Existing PPO Ontology" in response.text
    assert "Export / Visualization" in response.text


def test_browser_subpages_serve_html(client):
    for path, marker in [
        ("/config", "Zotero API Configuration"),
        ("/zotero", "Literature Records"),
        ("/literature", "Literature Records"),
        ("/ontology", "Existing PPO Ontology"),
        ("/curation", "Candidate Curation"),
        ("/export", "Export / Visualization"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text


def test_config_status_masks_saved_secrets(client):
    zotero = client.post(
        "/api/config/zotero",
        json={
            "library_type": "user",
            "library_id": "12345",
            "api_key": "zotero-secret",
            "collection_key": "ABC",
        },
    )
    llm = client.post(
        "/api/config/llm",
        json={
            "provider": "openai",
            "api_key": "llm-secret",
            "model": "gpt-test",
            "base_url": "https://example.test/v1",
        },
    )

    assert zotero.status_code == 200
    assert llm.status_code == 200
    status = client.get("/api/config/status").json()

    assert status["zotero"]["configured"] is True
    assert status["zotero"]["api_key"] == "configured"
    assert status["llm"]["configured"] is True
    assert status["llm"]["api_key"] == "configured"
    assert "zotero-secret" not in json.dumps(status)
    assert "llm-secret" not in json.dumps(status)
    saved = client.get("/api/config/saved").json()
    assert len(saved) == 2
    assert "zotero-secret" not in json.dumps(saved)
    assert "llm-secret" not in json.dumps(saved)
    assert saved[0]["api_key"]
    with db_session.SessionLocal() as session:
        assert session.get(AppSetting, "zotero_api_key").value == "zotero-secret"


def test_saved_api_config_activate_and_delete(client):
    created = client.post(
        "/api/config/saved",
        json={
            "kind": "llm",
            "alias": "Local model",
            "provider": "openai-compatible",
            "api_key": "sk-test123456",
            "model": "test-model",
            "base_url": "http://localhost:8080/v1",
        },
    )
    config_id = created.json()["id"]

    activated = client.post(f"/api/config/saved/{config_id}/activate", json={})
    deleted = client.delete(f"/api/config/saved/{config_id}")

    assert activated.status_code == 200
    assert activated.json()["active"] is True
    assert "sk-test123456" not in json.dumps(activated.json())
    assert deleted.status_code == 200


def test_create_update_review_and_export_candidate(client):
    document_response = client.post(
        "/api/literature",
        json={"filename": "note.txt", "content": "Preferential hydration stabilizes proteins."},
    )
    assert document_response.status_code == 200
    document_id = document_response.json()["id"]

    created = client.post(
        "/api/candidates",
        json={
            "document_id": document_id,
            "label": "preferential hydration",
            "proposed_definition": "A protein-solvent interaction concept.",
            "synonyms": ["water of preferential hydration"],
            "source_evidence": "Preferential hydration stabilizes proteins.",
        },
    )
    assert created.status_code == 200
    candidate_id = created.json()["id"]

    updated = client.patch(
        f"/api/candidates/{candidate_id}",
        json={"curator_rationale": "Supported by the source text.", "mappings": ["PMID:123"]},
    )
    assert updated.status_code == 200
    assert updated.json()["mappings"] == ["PMID:123"]

    reviewed = client.post(
        f"/api/candidates/{candidate_id}/review",
        json={"status": "approved", "rationale": "Ready for template export."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "approved"

    export = client.get("/api/exports/approved.robot.tsv")
    assert export.status_code == 200
    assert "preferential hydration" in export.text
    assert "water of preferential hydration" in export.text

    active = client.get("/api/candidates").json()
    assert all(candidate["id"] != candidate_id for candidate in active)


def test_approved_and_rejected_candidates_leave_active_queue(client):
    approved = client.post("/api/candidates", json={"label": "approve me"}).json()
    rejected = client.post("/api/candidates", json={"label": "reject me"}).json()
    deferred = client.post("/api/candidates", json={"label": "keep me deferred"}).json()

    client.post(f"/api/candidates/{approved['id']}/review", json={"status": "approved"})
    client.post(f"/api/candidates/{rejected['id']}/review", json={"status": "rejected"})
    client.post(f"/api/candidates/{deferred['id']}/review", json={"status": "deferred"})

    active_ids = {candidate["id"] for candidate in client.get("/api/candidates").json()}
    all_ids = {candidate["id"] for candidate in client.get("/api/candidates?include_rejected=true").json()}

    assert approved["id"] not in active_ids
    assert rejected["id"] not in active_ids
    assert deferred["id"] in active_ids
    assert {approved["id"], rejected["id"], deferred["id"]}.issubset(all_ids)


def test_refine_creates_candidate_from_guidance(client):
    response = client.post(
        "/api/refine",
        json={"guidance": "preferential exclusion\nFocus on solvent effects."},
    )

    assert response.status_code == 200
    assert response.json()["candidate"]["label"] == "preferential exclusion"
    assert response.json()["candidate"]["review_status"] == "in_review"


def test_import_test_zotero_entries_and_mock_extract(client):
    imported = client.post("/api/zotero/import-test", json={})

    assert imported.status_code == 200
    assert imported.json()["inserted"] == 2
    entries = client.get("/api/zotero/entries")
    assert entries.status_code == 200
    assert len(entries.json()) == 2
    source_id = entries.json()[0]["id"]

    extracted = client.post(
        "/api/extraction/candidates",
        json={"source_id": source_id, "guidance": "preferential hydration", "use_llm": False},
    )

    assert extracted.status_code == 200
    assert extracted.json()["used_llm"] is False
    assert extracted.json()["inserted"] >= 1
    assert extracted.json()["candidates"]
    with db_session.SessionLocal() as session:
        source = session.get(LiteratureSource, source_id)
        document = session.scalar(select(LiteratureDocument).where(LiteratureDocument.source_id == source_id))
    assert source.title
    assert document is not None


def test_zotero_sync_uses_saved_config_and_imports_entries(client, monkeypatch):
    class FakeZoteroClient:
        def __init__(self, config):
            assert config.library_type == "group"
            assert config.library_id == "999"
            assert config.api_key == "secret"

        def fetch_items(self, *, collection_key=None, limit=None):
            assert limit is None
            return [
                {
                    "key": "LIVEKEY",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Live Zotero test record",
                        "date": "2026",
                        "abstractNote": "Preferential interaction source text.",
                    },
                }
            ]

    import backend.app.api.routes as routes

    monkeypatch.setattr(routes, "ZoteroApiClient", FakeZoteroClient)
    client.post(
        "/api/config/zotero",
        json={"library_type": "group", "library_id": "999", "api_key": "secret"},
    )

    synced = client.post("/api/zotero/sync", json={})

    assert synced.status_code == 200
    assert synced.json()["fetched"] == 1
    assert client.get("/api/zotero/entries").json()[0]["title"] == "Live Zotero test record"


def test_zotero_sync_handles_incomplete_non_string_fields(client, monkeypatch):
    class FakeZoteroClient:
        def __init__(self, config):
            pass

        def fetch_items(self, *, collection_key=None, limit=None):
            return [
                {
                    "key": "ODDKEY",
                    "data": {
                        "itemType": "journalArticle",
                        "title": 12345,
                        "date": None,
                        "DOI": None,
                        "creators": [{"firstName": None, "lastName": 678}],
                        "abstractNote": {"summary": "structured"},
                    },
                }
            ]

    import backend.app.api.routes as routes

    monkeypatch.setattr(routes, "ZoteroApiClient", FakeZoteroClient)
    client.post("/api/config/zotero", json={"library_type": "user", "library_id": "1"})

    synced = client.post("/api/zotero/sync", json={})
    entry = client.get("/api/zotero/entries").json()[0]

    assert synced.status_code == 200
    assert synced.json()["inserted"] == 1
    assert entry["title"] == "12345"
    assert entry["provider_item_key"] == "ODDKEY"
    assert entry["zotero_select_uri"] == "zotero://select/library/items/ODDKEY"


def test_zotero_sync_accepts_optional_test_limit(client, monkeypatch):
    class FakeZoteroClient:
        def __init__(self, config):
            pass

        def fetch_items(self, *, collection_key=None, limit=None):
            assert limit == 2
            return []

    import backend.app.api.routes as routes

    monkeypatch.setattr(routes, "ZoteroApiClient", FakeZoteroClient)
    client.post("/api/config/zotero", json={"library_type": "user", "library_id": "1"})

    synced = client.post("/api/zotero/sync", json={"limit": 2})

    assert synced.status_code == 200


def test_static_javascript_uses_safe_normalization():
    script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert ".casefold(" not in script
    assert "function normalizeText" in script
    assert ".toLowerCase()" in script


def test_static_ui_has_current_routes_theme_and_literature_json_controls():
    static_dir = Path(__file__).parents[1] / "app" / "static"
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    script = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "styles.css").read_text(encoding="utf-8")

    for route in ["/config", "/zotero", "/ontology", "/curation", "/export"]:
        assert f'href="{route}"' in html
    assert 'class="logo"' in html
    assert "/static/app.js?v=" in html
    assert "/static/styles.css?v=" in html
    assert "object-fit: contain" in styles
    assert "APP_ROUTES" in script
    assert "ACTIVE_CANDIDATE_STATUSES" in script
    assert "No active candidates need curation." in script
    assert "history.pushState" in script
    assert "localStorage.setItem(\"oca-theme\"" in script
    assert "Show JSON section" in script
    assert "Open in Zotero" in script


def test_parse_ols_response_scores_and_flags_match():
    payload = {
        "response": {
            "docs": [
                {
                    "label": "preferential hydration",
                    "ontology_name": "ppo",
                    "iri": "http://example.org/PPO_0001",
                    "short_form": "PPO_0001",
                    "description": ["Existing term."],
                }
            ]
        }
    }

    matches = parse_ols_search_response("Preferential Hydration", payload)

    assert len(matches) == 1
    assert matches[0].score == 1.0
    assert matches[0].should_map_existing is True
    assert matches[0].description == "Existing term."


def test_ols_service_uses_public_search_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "preferential hydration"
        return httpx.Response(
            200,
            json={
                "response": {
                    "docs": [
                        {
                            "label": "preferential hydration",
                            "ontology_name": "ppo",
                            "iri": "http://example.org/PPO_0001",
                        }
                    ]
                }
            },
        )

    service = OlsLookupService(client=httpx.Client(transport=httpx.MockTransport(handler)))

    matches = service.search("preferential hydration")

    assert matches[0].ontology_id == "ppo"


def test_api_ols_lookup_does_not_auto_select_first_match(client, monkeypatch):
    class FakeOlsService:
        def search(self, label: str):
            assert label == "candidate"

            class Match:
                def to_dict(self):
                    return {
                        "label": "candidate",
                        "ontology_id": "test",
                        "iri": "http://example.org/TEST_1",
                        "term_id": "TEST_1",
                        "description": None,
                        "score": 1.0,
                        "should_map_existing": True,
                    }

            return [Match()]

    import backend.app.api.routes as routes

    monkeypatch.setattr(routes, "OlsLookupService", FakeOlsService)
    created = client.post("/api/candidates", json={"label": "candidate"})
    candidate_id = created.json()["id"]

    checked = client.post(f"/api/candidates/{candidate_id}/ols", json={})

    assert checked.status_code == 200
    assert checked.json()["selected_ols"] is None
    assert checked.json()["ols_lookup_status"] == "performed"
    assert checked.json()["curator_decision"] == "needs_review"

    selected = client.post(
        f"/api/candidates/{candidate_id}/ols-selection",
        json={"match": checked.json()["ols_matches"][0]},
    )
    assert selected.json()["selected_ols"]["term_id"] == "TEST_1"

    cleared = client.post(f"/api/candidates/{candidate_id}/ols-selection", json={"match": None})
    assert cleared.status_code == 200
    assert cleared.json()["selected_ols"] is None
    with db_session.SessionLocal() as session:
        record = session.scalar(select(CandidateTermRecord))
        document = session.scalar(select(LiteratureDocument))
    assert record.selected_ols_json is None
    assert document.filename == "Manual browser candidates"


def test_ontology_folder_scan_and_turtle_index(client, tmp_path):
    ontology_dir = tmp_path / "ppo"
    ontology_dir.mkdir()
    ontology_file = ontology_dir / "ppo.ttl"
    ontology_file.write_text(
        """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix oboInOwl: <http://www.geneontology.org/formats/oboInOwl#> .
<http://example.org/PPO_0001> a owl:Class ;
  rdfs:label "preferential hydration" ;
  <http://purl.obolibrary.org/obo/IAO_0000115> "A local PPO definition." ;
  oboInOwl:hasExactSynonym "water of preferential hydration" .
""",
        encoding="utf-8",
    )

    scan = scan_ontology_folder(ontology_dir)
    terms = index_ontology_file(ontology_file)

    assert scan["readable"] is True
    assert scan["files"][0]["name"] == "ppo.ttl"
    assert terms[0].label == "preferential hydration"
    assert terms[0].definition == "A local PPO definition."

    saved = client.post("/api/config/ontology-path", json={"path": str(ontology_dir)})
    selected = client.post("/api/ontology/select-file", json={"path": str(ontology_file)})
    indexed = client.post("/api/ontology/index")
    search = client.get("/api/ontology/search", params={"q": "hydration"})

    assert saved.status_code == 200
    assert selected.status_code == 200
    assert indexed.json()["term_count"] == 1
    assert search.json()[0]["label"] == "preferential hydration"


def test_ontology_and_meta_graph_endpoints(client, tmp_path):
    ontology_dir = tmp_path / "ppo"
    ontology_dir.mkdir()
    ontology_file = ontology_dir / "ppo.tsv"
    ontology_file.write_text(
        "ID\tLABEL\tparent\nPPO:0001\tpreferential hydration\tPPO:0000\n",
        encoding="utf-8",
    )
    client.post("/api/config/ontology-path", json={"path": str(ontology_dir)})
    client.post("/api/ontology/select-file", json={"path": str(ontology_file)})

    ontology_graph = client.get("/api/ontology/graph").json()
    meta_graph = client.get("/api/meta-ontology/graph").json()

    assert ontology_graph["nodes"]
    assert ontology_graph["edges"][0]["label"] == "subClassOf"
    assert meta_graph["nodes"]
    assert meta_graph["edges"]


def test_local_ontology_match_defaults_to_no_selection(client, tmp_path):
    ontology_dir = tmp_path / "ppo"
    ontology_dir.mkdir()
    ontology_file = ontology_dir / "ppo.tsv"
    ontology_file.write_text(
        "ID\tLABEL\tdefinition\nPPO:0001\tpreferential hydration\tExisting local term.\n",
        encoding="utf-8",
    )
    client.post("/api/config/ontology-path", json={"path": str(ontology_dir)})
    client.post("/api/ontology/select-file", json={"path": str(ontology_file)})
    created = client.post("/api/candidates", json={"label": "preferential hydration"})
    candidate_id = created.json()["id"]

    matched = client.post(f"/api/candidates/{candidate_id}/match-local-ontology", json={})

    assert matched.status_code == 200
    assert matched.json()["local_lookup_status"] == "performed"
    assert matched.json()["local_matches"]
    assert matched.json()["selected_local"] is None

    selected = client.post(
        f"/api/candidates/{candidate_id}/select-local-match",
        json={"match": matched.json()["local_matches"][0]},
    )
    assert selected.json()["curator_decision"] == "use_existing_local_term"


def test_export_includes_match_and_decision_fields(client):
    document_response = client.post(
        "/api/literature",
        json={"filename": "note.txt", "content": "Preferential hydration stabilizes proteins."},
    )
    created = client.post(
        "/api/candidates",
        json={
            "document_id": document_response.json()["id"],
            "label": "preferential hydration",
            "source_evidence": "Preferential hydration stabilizes proteins.",
        },
    )
    candidate_id = created.json()["id"]
    client.patch(
        f"/api/candidates/{candidate_id}",
        json={
            "selected_ols": {"label": "external term", "ontology_id": "test", "iri": "http://ols"},
            "selected_local": {"label": "local term", "iri": "PPO:0001"},
            "curator_decision": "propose_new_term",
        },
    )
    client.post(f"/api/candidates/{candidate_id}/review", json={"status": "approved"})

    export = client.get("/api/exports/approved.candidates.tsv")

    assert "selected_local_iri" in export.text
    assert "selected_ols_iri" in export.text
    assert "curator_decision" in export.text
    assert "PPO:0001" in export.text


def test_permanent_rejection_excludes_active_queue_and_can_restore(client):
    created = client.post("/api/candidates", json={"label": "reject me"})
    candidate_id = created.json()["id"]

    rejected = client.post(
        f"/api/candidates/{candidate_id}/permanent-reject",
        json={"reason": "duplicate"},
    )
    active = client.get("/api/candidates").json()
    rejected_list = client.get("/api/candidates/rejected").json()
    restored = client.post(f"/api/candidates/{candidate_id}/restore", json={})

    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "permanently_rejected"
    assert all(candidate["id"] != candidate_id for candidate in active)
    assert rejected_list[0]["rejection_reason"] == "duplicate"
    assert restored.json()["review_status"] == "in_review"
