import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from backend.app.cli import app
from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.models.db import LiteratureSource
from backend.app.zotero.client import (
    ZoteroApiClient,
    ZoteroApiConfig,
    ZoteroAuthenticationError,
    ZoteroConfigError,
    ZoteroNotFoundError,
)
from backend.app.zotero.importer import parse_source_item


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
    get_settings.cache_clear()

    db_session.Base.metadata.create_all(bind=engine)
    yield session_factory
    get_settings.cache_clear()


def zotero_item(*, title: str = "Protein-solvent preferential interactions") -> dict:
    return {
        "key": "ITEMKEY123",
        "version": 42,
        "data": {
            "key": "ITEMKEY123",
            "itemType": "journalArticle",
            "title": title,
            "creators": [
                {
                    "creatorType": "author",
                    "firstName": "Serge N.",
                    "lastName": "Timasheff",
                }
            ],
            "date": "2002",
            "DOI": "https://doi.org/10.1073/pnas.122225399",
            "url": "https://www.pnas.org/doi/10.1073/pnas.122225399",
            "abstractNote": "Solvent additives modulate biochemical reactions.",
            "collections": ["COLLECTIONKEY"],
            "tags": [{"tag": "protein hydration"}],
            "extra": "Citation Key: timasheff2002ProteinSolventPreferential",
        },
    }


def test_zotero_api_url_construction() -> None:
    user_client = ZoteroApiClient(
        ZoteroApiConfig(library_type="user", library_id="123", base_url="https://api.zotero.org")
    )
    group_client = ZoteroApiClient(
        ZoteroApiConfig(library_type="group", library_id="456", base_url="https://api.zotero.org")
    )

    assert user_client.build_items_url() == "https://api.zotero.org/users/123/items"
    assert group_client.build_items_url() == "https://api.zotero.org/groups/456/items"
    assert (
        user_client.build_items_url("COLL")
        == "https://api.zotero.org/users/123/collections/COLL/items"
    )
    assert (
        group_client.build_items_url("COLL")
        == "https://api.zotero.org/groups/456/collections/COLL/items"
    )


def test_zotero_api_header_construction_and_config_output(monkeypatch) -> None:
    client = ZoteroApiClient(
        ZoteroApiConfig(library_type="user", library_id="123", api_key="super-secret")
    )
    headers = client.build_headers()

    assert headers["Zotero-API-Version"] == "3"
    assert headers["Zotero-API-Key"] == "super-secret"

    no_key_client = ZoteroApiClient(ZoteroApiConfig(library_type="user", library_id="123"))
    assert "Zotero-API-Key" not in no_key_client.build_headers()

    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_TYPE", "user")
    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_ID", "123")
    monkeypatch.setenv("OCA_ZOTERO_API_KEY", "super-secret")
    get_settings.cache_clear()

    result = runner.invoke(app, ["zotero-config"])

    assert result.exit_code == 0
    assert "API key configured:" in result.output
    assert "super-secret" not in result.output


def test_zotero_api_json_normalization_skips_non_bibliographic_items() -> None:
    source = parse_source_item(zotero_item())
    attachment = parse_source_item(
        {"key": "ATTACHMENT", "data": {"itemType": "attachment", "title": "PDF"}}
    )
    note = parse_source_item({"key": "NOTE", "data": {"itemType": "note", "title": "Note"}})
    annotation = parse_source_item(
        {"key": "ANNOTATION", "data": {"itemType": "annotation", "title": "Annotation"}}
    )

    assert source is not None
    assert source.provider_item_key == "ITEMKEY123"
    assert source.citation_key == "timasheff2002ProteinSolventPreferential"
    assert source.zotero_version == 42
    assert source.item_type == "journalArticle"
    assert source.year == "2002"
    assert source.doi == "10.1073/pnas.122225399"
    assert source.creators[0]["family"] == "Timasheff"
    assert source.tags == ["protein hydration"]
    assert source.collections == ["COLLECTIONKEY"]
    assert attachment is None
    assert note is None
    assert annotation is None


def test_zotero_sync_dry_run_fetches_and_persists_nothing(isolated_db, monkeypatch):
    from backend.app.zotero.client import ZoteroApiClient

    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_TYPE", "user")
    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_ID", "123")
    get_settings.cache_clear()
    monkeypatch.setattr(ZoteroApiClient, "fetch_items", lambda self, **kwargs: [zotero_item()])

    result = runner.invoke(app, ["zotero-sync", "--dry-run"])

    assert result.exit_code == 0
    assert "Importable sources:" in result.output
    assert "Dry run" in result.output
    with isolated_db() as session:
        sources = session.scalars(select(LiteratureSource)).all()
    assert sources == []


def test_zotero_sync_persists_and_updates_without_duplicates(isolated_db, monkeypatch):
    from backend.app.zotero.client import ZoteroApiClient

    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_TYPE", "user")
    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_ID", "123")
    get_settings.cache_clear()
    monkeypatch.setattr(
        ZoteroApiClient,
        "fetch_items",
        lambda self, **kwargs: [zotero_item(title="Initial title")],
    )
    first = runner.invoke(app, ["zotero-sync"])

    monkeypatch.setattr(
        ZoteroApiClient,
        "fetch_items",
        lambda self, **kwargs: [zotero_item(title="Updated title")],
    )
    second = runner.invoke(app, ["zotero-sync"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Updated:" in second.output
    with isolated_db() as session:
        sources = session.scalars(select(LiteratureSource)).all()
    assert len(sources) == 1
    assert sources[0].title == "Updated title"
    assert sources[0].zotero_version == 42
    assert sources[0].synced_at is not None


def test_zotero_sync_cli_overrides_and_collection(isolated_db, monkeypatch):
    from backend.app.zotero.client import ZoteroApiClient

    calls = []

    def fake_fetch(self, **kwargs):
        calls.append((self.config.library_type, self.config.library_id, kwargs.get("collection_key")))
        return [zotero_item()]

    monkeypatch.setattr(ZoteroApiClient, "fetch_items", fake_fetch)
    result = runner.invoke(
        app,
        [
            "zotero-sync",
            "--library-type",
            "group",
            "--library-id",
            "456",
            "--collection",
            "COLLECTIONKEY",
            "--limit",
            "1",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("group", "456", "COLLECTIONKEY")]
    assert "group library 456" in result.output
    assert "COLLECTIONKEY" in result.output


def test_zotero_sync_config_errors_are_clear(monkeypatch):
    get_settings.cache_clear()
    missing_id = runner.invoke(app, ["zotero-sync", "--library-type", "user"])
    invalid_type = runner.invoke(
        app,
        ["zotero-sync", "--library-type", "personal", "--library-id", "123"],
    )

    assert missing_id.exit_code != 0
    assert "library id is required" in missing_id.output
    assert invalid_type.exit_code != 0
    assert "library type must be 'user' or 'group'" in invalid_type.output


def test_zotero_api_http_errors_are_clear() -> None:
    auth_transport = httpx.MockTransport(lambda request: httpx.Response(401, json=[]))
    not_found_transport = httpx.MockTransport(lambda request: httpx.Response(404, json=[]))

    auth_client = ZoteroApiClient(
        ZoteroApiConfig(library_type="user", library_id="123"),
        http_client=httpx.Client(transport=auth_transport),
    )
    not_found_client = ZoteroApiClient(
        ZoteroApiConfig(library_type="group", library_id="456"),
        http_client=httpx.Client(transport=not_found_transport),
    )

    with pytest.raises(ZoteroAuthenticationError, match="authentication"):
        auth_client.fetch_items()
    with pytest.raises(ZoteroNotFoundError, match="not found"):
        not_found_client.fetch_items()


def test_zotero_api_invalid_config_raises() -> None:
    with pytest.raises(ZoteroConfigError, match="library type"):
        ZoteroApiClient(ZoteroApiConfig(library_type="personal", library_id="123"))
    with pytest.raises(ZoteroConfigError, match="library id"):
        ZoteroApiClient(ZoteroApiConfig(library_type="user", library_id=None))


def test_zotero_api_invalid_json_raises() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"not json"))
    client = ZoteroApiClient(
        ZoteroApiConfig(library_type="user", library_id="123"),
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(Exception, match="invalid JSON"):
        client.fetch_items()


def test_zotero_api_pagination() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=[zotero_item(title="First")],
                headers={"Link": '<https://api.zotero.org/users/123/items?start=1>; rel="next"'},
            )
        return httpx.Response(200, json=[zotero_item(title="Second")])

    client = ZoteroApiClient(
        ZoteroApiConfig(library_type="user", library_id="123"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    items = client.fetch_items()

    assert len(items) == 2
    assert len(requests) == 2


def test_zotero_sync_triggers_pipeline_automatically(isolated_db, monkeypatch, tmp_path):
    from backend.app.zotero.client import ZoteroApiClient
    import backend.app.literature.pipeline as pipeline

    calls = []

    def fake_run(config):
        calls.append(config)
        from backend.app.literature.pipeline import LiteraturePipelineResult
        return LiteraturePipelineResult(
            combined_output_file=tmp_path / "combined.md",
            copied_pdf_count=5,
            converted_markdown_count=5,
            failed_pdf_count=0,
            created_paper_markdown_count=5,
            structured_markdown_count=5,
            combined_markdown_count=5,
        )

    monkeypatch.setattr(pipeline, "run_literature_pipeline", fake_run)
    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_TYPE", "user")
    monkeypatch.setenv("OCA_ZOTERO_LIBRARY_ID", "123")
    monkeypatch.setenv("OCA_ZOTERO_LITERATURE_STORAGE_PATH", str(tmp_path / "storage"))
    get_settings.cache_clear()

    monkeypatch.setattr(ZoteroApiClient, "fetch_items", lambda self, **kwargs: [zotero_item()])

    result = runner.invoke(app, ["zotero-sync"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].zotero_literature_storage_path == tmp_path / "storage"

