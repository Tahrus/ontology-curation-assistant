import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from backend.app.cli import app
from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.models.db import AppSetting, LiteratureDocument, LiteratureSource


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


def write_csl_export(tmp_path: Path, *, title: str | None = None, doi: str | None = None) -> Path:
    metadata_path = tmp_path / "zotero-export.json"
    item = {
        "id": "ITEMKEY123",
        "citationKey": "timasheff2002ProteinSolventPreferential",
        "title": title
        or (
            "Protein-solvent preferential interactions, protein hydration, and the "
            "modulation of biochemical reactions by solvent components"
        ),
        "author": [{"family": "Timasheff", "given": "Serge N."}],
        "issued": {"date-parts": [[2002]]},
        "DOI": doi or "10.1073/pnas.122225399",
        "URL": "https://www.pnas.org/doi/10.1073/pnas.122225399",
        "abstract": "Solvent additives modulate biochemical reactions.",
        "tag": ["protein hydration", "preferential interaction"],
        "collection": ["osmolytes"],
    }
    metadata_path.write_text(json.dumps([item]), encoding="utf-8")
    return metadata_path


def insert_document(
    session_factory,
    path: Path,
    content: str,
    *,
    source_id: int | None = None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    with session_factory() as session:
        document = LiteratureDocument.from_path(path)
        document.source_id = source_id
        session.add(document)
        session.commit()
        return document.id


def insert_source(
    session_factory,
    *,
    title: str,
    citation_key: str | None = None,
    doi: str | None = None,
) -> int:
    from backend.app.zotero.importer import normalize_doi, normalize_title

    with session_factory() as session:
        source = LiteratureSource(
            provider="zotero",
            provider_item_key=citation_key,
            citation_key=citation_key,
            title=title,
            normalized_title=normalize_title(title),
            creators_json="[]",
            year="2002",
            doi=normalize_doi(doi),
            normalized_doi=normalize_doi(doi),
            tags_json="[]",
            collections_json="[]",
        )
        session.add(source)
        session.commit()
        return source.id


def test_csl_json_import_inserts_valid_item_and_skips_missing_title(isolated_db, tmp_path):
    metadata_path = tmp_path / "zotero-export.json"
    metadata_path.write_text(
        json.dumps(
            [
                {
                    "id": "ITEMKEY123",
                    "citationKey": "timasheff2002ProteinSolventPreferential",
                    "title": "Protein-solvent preferential interactions",
                    "author": [{"family": "Timasheff", "given": "Serge N."}],
                    "issued": {"date-parts": [[2002]]},
                },
                {"id": "NO_TITLE"},
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["zotero-import", str(metadata_path)])

    assert result.exit_code == 0
    assert "Inserted:" in result.output
    assert "Skipped:" in result.output
    with isolated_db() as session:
        sources = session.scalars(select(LiteratureSource)).all()
    assert len(sources) == 1
    assert sources[0].title == "Protein-solvent preferential interactions"


def test_csl_json_import_accepts_missing_optional_fields(isolated_db, tmp_path):
    metadata_path = tmp_path / "minimal-zotero-export.json"
    metadata_path.write_text(json.dumps([{"id": "ITEMKEY123", "title": "Minimal title"}]))

    result = runner.invoke(app, ["zotero-import", str(metadata_path)])

    assert result.exit_code == 0
    with isolated_db() as session:
        source = session.scalar(select(LiteratureSource))
    assert source is not None
    assert source.title == "Minimal title"
    assert source.doi is None


def test_duplicate_import_updates_without_creating_duplicate(isolated_db, tmp_path):
    metadata_path = write_csl_export(tmp_path, title="Initial title")
    first = runner.invoke(app, ["zotero-import", str(metadata_path)])

    metadata_path = write_csl_export(tmp_path, title="Updated title")
    second = runner.invoke(app, ["zotero-import", str(metadata_path)])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Updated:" in second.output
    with isolated_db() as session:
        sources = session.scalars(select(LiteratureSource)).all()
    assert len(sources) == 1
    assert sources[0].title == "Updated title"


def test_zotero_list_empty_and_with_source(isolated_db, tmp_path):
    empty = runner.invoke(app, ["zotero-list"])
    assert empty.exit_code == 0
    assert "No Zotero source records found" in empty.output

    metadata_path = write_csl_export(tmp_path)
    import_result = runner.invoke(app, ["zotero-import", str(metadata_path)])
    listed = runner.invoke(app, ["zotero-list"])

    assert import_result.exit_code == 0
    assert listed.exit_code == 0
    assert "timasheff2002ProteinSolventPreferential" in listed.output
    assert "10.1073/pnas.122225399" in listed.output


def test_zotero_show_full_metadata_and_missing_id(isolated_db, tmp_path):
    metadata_path = write_csl_export(tmp_path)
    assert runner.invoke(app, ["zotero-import", str(metadata_path)]).exit_code == 0

    with isolated_db() as session:
        source = session.scalar(select(LiteratureSource))

    shown = runner.invoke(app, ["zotero-show", str(source.id)])
    missing = runner.invoke(app, ["zotero-show", "999999"])

    assert shown.exit_code == 0
    assert "Serge N." in shown.output
    assert "protein hydration" in shown.output
    assert "osmolytes" in shown.output
    assert missing.exit_code != 0
    assert "No Zotero source found" in missing.output


def test_link_documents_by_citation_key_in_filename(isolated_db, tmp_path):
    literature_dir = tmp_path / "literature"
    source_id = insert_source(
        isolated_db,
        title="Protein-solvent preferential interactions",
        citation_key="timasheff2002ProteinSolventPreferential",
    )
    document_id = insert_document(
        isolated_db,
        literature_dir / "timasheff2002ProteinSolventPreferential.pdf.txt",
        "Document text.",
    )

    result = runner.invoke(app, ["zotero-link-documents", str(literature_dir)])

    assert result.exit_code == 0
    assert "Linked:" in result.output
    with isolated_db() as session:
        document = session.get(LiteratureDocument, document_id)
    assert document.source_id == source_id


def test_link_documents_by_doi_in_content(isolated_db, tmp_path):
    literature_dir = tmp_path / "literature"
    source_id = insert_source(
        isolated_db,
        title="Protein-solvent preferential interactions",
        doi="https://doi.org/10.1073/pnas.122225399",
    )
    document_id = insert_document(
        isolated_db,
        literature_dir / "paper.txt",
        "This paper is available at doi:10.1073/pnas.122225399.",
    )

    result = runner.invoke(app, ["zotero-link-documents", str(literature_dir)])

    assert result.exit_code == 0
    with isolated_db() as session:
        document = session.get(LiteratureDocument, document_id)
    assert document.source_id == source_id


def test_ambiguous_document_matches_are_skipped(isolated_db, tmp_path):
    literature_dir = tmp_path / "literature"
    insert_source(isolated_db, title="Shared title", citation_key="sharedA")
    insert_source(isolated_db, title="Shared title", citation_key="sharedB")
    document_id = insert_document(
        isolated_db,
        literature_dir / "paper.txt",
        "The article title is Shared title.",
    )

    result = runner.invoke(app, ["zotero-link-documents", str(literature_dir)])

    assert result.exit_code == 0
    assert "Ambiguous:" in result.output
    with isolated_db() as session:
        document = session.get(LiteratureDocument, document_id)
    assert document.source_id is None


def test_existing_link_not_overwritten_unless_force(isolated_db, tmp_path):
    literature_dir = tmp_path / "literature"
    old_source_id = insert_source(isolated_db, title="Old source", citation_key="oldKey")
    new_source_id = insert_source(isolated_db, title="New source", citation_key="newKey")
    document_id = insert_document(
        isolated_db,
        literature_dir / "newKey.txt",
        "Document text.",
        source_id=old_source_id,
    )

    without_force = runner.invoke(app, ["zotero-link-documents", str(literature_dir)])
    with isolated_db() as session:
        document = session.get(LiteratureDocument, document_id)
        assert document.source_id == old_source_id

    with_force = runner.invoke(
        app,
        ["zotero-link-documents", str(literature_dir), "--force"],
    )

    assert without_force.exit_code == 0
    assert with_force.exit_code == 0
    with isolated_db() as session:
        document = session.get(LiteratureDocument, document_id)
    assert document.source_id == new_source_id


def test_literature_list_shows_linked_source(isolated_db, tmp_path):
    literature_dir = tmp_path / "literature"
    source_id = insert_source(
        isolated_db,
        title="Protein-solvent preferential interactions",
        citation_key="timasheff2002ProteinSolventPreferential",
    )
    insert_document(
        isolated_db,
        literature_dir / "paper.txt",
        "Document text.",
        source_id=source_id,
    )

    result = runner.invoke(app, ["literature-list"])

    assert result.exit_code == 0
    assert "source=timasheff2002ProteinSolventPreferential" in result.output


def test_ingest_writes_literature_json_with_full_text(isolated_db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_dir = tmp_path / "source-files"
    source_dir.mkdir()
    source_file = source_dir / "paper.txt"
    source_file.write_text("Alpha  beta\n\n\nGamma scientific text.", encoding="utf-8")

    result = runner.invoke(app, ["ingest", str(source_dir)])

    output_path = tmp_path / "literature" / "literature.json"
    assert result.exit_code == 0
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    record = payload["papers"][0]
    assert payload["source"] == "Ontology Curation Assistant literature library"
    assert payload["schema_version"] == "1.0"
    assert record["paper_id"]
    assert record["citation"]["title"] == "paper.txt"
    assert record["full_text"] == "Alpha beta\n\nGamma scientific text."
    assert record["sections"]["introduction"] == record["full_text"]
    assert record["chunks"][0]["paper_id"] == record["paper_id"]
    assert record["attachments"][0]["text_extracted"] is True
    assert record["quality_flags"] == []


def test_literature_json_preserves_metadata_flags_and_deduplicates(isolated_db, tmp_path):
    from backend.app.literature.exporter import export_literature_json

    source_id = insert_source(
        isolated_db,
        title="Protein-solvent preferential interactions",
        citation_key="ITEMKEY123",
        doi="10.1073/pnas.122225399",
    )
    insert_document(
        isolated_db,
        tmp_path / "documents" / "paper.txt",
        "Full text for LLM analysis.",
        source_id=source_id,
    )
    insert_source(
        isolated_db,
        title="Duplicate by DOI",
        citation_key="OTHERKEY",
        doi="10.1073/pnas.122225399",
    )
    insert_source(
        isolated_db,
        title="Metadata only source",
        citation_key="MISSATT1",
    )

    with isolated_db() as session:
        output_path = export_literature_json(session, tmp_path / "literature" / "literature.json")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    titles = [record["citation"]["title"] for record in payload["papers"]]
    rich_record = next(record for record in payload["papers"] if record["zotero"]["item_key"] == "ITEMKEY123")
    missing_record = next(record for record in payload["papers"] if record["zotero"]["item_key"] == "MISSATT1")

    assert titles.count("Protein-solvent preferential interactions") == 1
    assert "Duplicate by DOI" not in titles
    assert rich_record["citation"]["doi"] == "10.1073/pnas.122225399"
    assert rich_record["citation"]["year"] == 2002
    assert rich_record["zotero"]["uri"] == "zotero://select/library/items/ITEMKEY123"
    assert rich_record["full_text"] == "Full text for LLM analysis."
    assert missing_record["full_text"] is None
    assert "missing_attachment" in missing_record["quality_flags"]
    assert "missing_full_text" in missing_record["quality_flags"]


def test_literature_json_extracts_sections_and_chunks_long_text(isolated_db, tmp_path):
    from backend.app.literature.exporter import export_literature_json

    source_id = insert_source(
        isolated_db,
        title="Structured paper",
        citation_key="STRUCT1",
        doi="10.1000/structured",
    )
    long_results = " ".join(["result"] * 900)
    insert_document(
        isolated_db,
        tmp_path / "documents" / "structured.txt",
        f"Introduction\nIntro text.\n\nMethods\nMethod text.\n\nResults\n{long_results}\n\nConclusion\nDone.",
        source_id=source_id,
    )

    with isolated_db() as session:
        output_path = export_literature_json(session, tmp_path / "literature" / "literature.json")

    paper = json.loads(output_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["sections"]["introduction"] == "Intro text."
    assert paper["sections"]["methodology"] == "Method text."
    assert paper["sections"]["results"].startswith("result")
    assert paper["sections"]["conclusion"] == "Done."
    assert len([chunk for chunk in paper["chunks"] if chunk["section"] == "results"]) > 1
    assert all("mythology" not in chunk["section"] for chunk in paper["chunks"])


def test_ambiguous_or_malformed_zotero_keys_do_not_create_links(isolated_db, tmp_path):
    from backend.app.literature.exporter import export_literature_json

    insert_source(isolated_db, title="Shared one", citation_key="SHARED1")
    insert_source(isolated_db, title="Shared two", citation_key="SHARED1")
    insert_source(isolated_db, title="Malformed", citation_key="not a key")

    with isolated_db() as session:
        payload = json.loads(export_literature_json(session, tmp_path / "literature.json").read_text(encoding="utf-8"))

    shared = [paper for paper in payload["papers"] if paper["source_metadata"]["citation_key"] == "SHARED1"]
    malformed = next(paper for paper in payload["papers"] if paper["citation"]["title"] == "Malformed")
    assert shared[0]["zotero"]["uri"] is None
    assert "duplicate_zotero_item_key" in shared[0]["zotero"]["diagnostics"]
    assert malformed["zotero"]["item_key"] is None
    assert "malformed_zotero_item_key" in malformed["zotero"]["diagnostics"]


def test_literature_json_uses_group_zotero_uri_when_configured(isolated_db, tmp_path):
    from backend.app.literature.exporter import export_literature_json

    insert_source(isolated_db, title="Group paper", citation_key="GROUPK1")
    with isolated_db() as session:
        session.add(AppSetting(key="zotero_library_type", value="group"))
        session.add(AppSetting(key="zotero_library_id", value="123456"))
        session.commit()
        payload = json.loads(export_literature_json(session, tmp_path / "literature.json").read_text(encoding="utf-8"))

    paper = payload["papers"][0]
    assert paper["zotero"]["uri"] == "zotero://select/groups/123456/items/GROUPK1"
    assert paper["zotero"]["library_id"] == "123456"
