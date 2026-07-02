from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.main import app
from backend.app.cli import app as cli_app
from backend.app.models.db import AppSetting, LiteratureSource

from backend.app.literature.canonical import (
    RepositoryPaths,
    build_combined,
    clean_llm_markdown,
    cleanup_unpromoted_staged,
    import_directory,
    import_identified_item,
    list_curated_entries,
    list_entries,
    normalize_doi,
    normalize_pii,
    promote_staged_entry,
    reset_repository,
    upload_manual_markdown,
    upsert_markdown,
)
from backend.app.literature.publisher_xml import (
    ArticleApiRetrievalFailed,
    ElsevierApiConfig,
    ElsevierArticleClient,
    ElsevierRetrieval,
    LiteratureIdentification,
    MissingApiConfigurationError,
    collect_article_identifiers,
    parse_elsevier_xml,
    retrieve_article_via_api_with_identifier_fallback,
)


ELSEVIER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/" xmlns:ce="http://www.elsevier.com/xml/common/dtd" xmlns:xocs="http://www.elsevier.com/xml/xocs/dtd">
  <coredata>
    <dc:title>Structured Protein Recovery</dc:title>
    <dc:creator>Ada Curator</dc:creator>
    <dc:creator>Ben Researcher</dc:creator>
    <prism:publicationName>Journal of Structured Bioprocessing</prism:publicationName>
    <prism:coverDate>2026-04-03</prism:coverDate>
    <prism:doi>10.1000/structured.xml</prism:doi>
    <xocs:pii-unformatted>S1234567890123456</xocs:pii-unformatted>
  </coredata>
  <originalText>
    <article>
      <head><ce:abstract><ce:para>Structured abstract text.</ce:para></ce:abstract></head>
      <body><ce:sections>
        <ce:section><ce:section-title>Introduction</ce:section-title><ce:para>XML body evidence.</ce:para>
          <ce:section><ce:section-title>Nested method</ce:section-title><ce:para>Nested section evidence.</ce:para></ce:section>
          <ce:figure><ce:caption>Recovery process figure.</ce:caption></ce:figure>
          <ce:table><ce:caption>Recovery values</ce:caption><ce:row><ce:entry>Condition</ce:entry><ce:entry>Yield</ce:entry></ce:row><ce:row><ce:entry>A</ce:entry><ce:entry>95%</ce:entry></ce:row></ce:table>
        </ce:section>
      </ce:sections></body>
      <ce:appendices><ce:appendix><ce:section-title>Appendix A</ce:section-title><ce:para>Appendix calibration details.</ce:para></ce:appendix></ce:appendices>
      <tail><ce:bibliography><ce:reference>Reference Author. Reference title. 2020.</ce:reference></ce:bibliography></tail>
    </article>
  </originalText>
</full-text-retrieval-response>
"""


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


def test_elsevier_xml_metadata_body_hierarchy_appendix_and_references() -> None:
    article = parse_elsevier_xml(ELSEVIER_XML)
    assert article.title == "Structured Protein Recovery"
    assert article.authors == ["Ada Curator", "Ben Researcher"]
    assert article.journal == "Journal of Structured Bioprocessing"
    assert article.year == "2026"
    assert article.doi == "10.1000/structured.xml"
    assert article.pii == "S1234567890123456"
    assert article.has_full_text is True
    assert "# Structured Protein Recovery" in article.markdown
    assert "## Introduction" in article.markdown
    assert "### Nested method" in article.markdown
    assert "**Figure:** Recovery process figure." in article.markdown
    assert "| Condition | Yield |" in article.markdown
    assert "## Appendix A" in article.markdown
    assert "Appendix calibration details." in article.markdown
    assert "## References" in article.markdown


@pytest.mark.parametrize(("doi", "pii", "expected_segment"), [("10.1000/structured.xml", None, "/doi/"), (None, "S1234567890123456", "/pii/")])
def test_elsevier_client_retrieves_xml_by_doi_or_pii(doi: str | None, pii: str | None, expected_segment: str) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=ELSEVIER_XML)

    retrieval = ElsevierArticleClient(
        ElsevierApiConfig(api_key="test-key", enabled=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).retrieve(doi=doi, pii=pii)
    assert retrieval.status == "success"
    assert retrieval.xml_text == ELSEVIER_XML.strip()
    assert expected_segment in requests[0].url.path
    assert requests[0].headers["Accept"] == "text/xml"
    assert "apiKey" not in requests[0].url.params


def test_elsevier_client_accepts_legacy_article_endpoint_base_url() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=ELSEVIER_XML)

    ElsevierArticleClient(
        ElsevierApiConfig(api_key="test-key", enabled=True, base_url="https://api.elsevier.com/content/article"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).retrieve(doi="10.1000/structured.xml")
    assert requests[0].url.path.count("/content/article") == 1


def test_collect_article_identifiers_normalizes_and_orders_zotero_metadata() -> None:
    identifiers = collect_article_identifiers(
        {
            "URL": " https://www.sciencedirect.com/science/article/pii/S0098135425001978 ",
            "DOI": "https://doi.org/10.1016/J.EXAMPLE.2026.1",
            "ISSN": "1234-5678",
            "ISBN": "978-1-2345-6789-0",
            "extra": "PMID: 123456\nPMCID: PMC7654321",
        }
    )
    assert [(item.kind, item.value) for item in identifiers] == [
        ("pii", "S0098135425001978"),
        ("doi", "10.1016/j.example.2026.1"),
        ("pmid", "123456"),
        ("pmcid", "PMC7654321"),
        ("isbn", "978-1-2345-6789-0"),
        ("issn", "1234-5678"),
        ("url", "https://www.sciencedirect.com/science/article/pii/S0098135425001978"),
    ]


def test_identifier_fallback_pii_success_prevents_doi_call() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=ELSEVIER_XML)

    result = retrieve_article_via_api_with_identifier_fallback(
        {"pii": "S1234567890123456", "doi": "10.1000/structured.xml"},
        ElsevierApiConfig(api_key="test-key", enabled=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result.used_identifier.kind == "pii"
    assert len(requests) == 1
    assert "/pii/" in requests[0].url.path


def test_identifier_fallback_recoverable_pii_failure_tries_doi() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404, text="not found") if "/pii/" in request.url.path else httpx.Response(200, text=ELSEVIER_XML)

    result = retrieve_article_via_api_with_identifier_fallback(
        {"pii": "S0000000000000000", "doi": "10.1000/structured.xml"},
        ElsevierApiConfig(api_key="test-key", enabled=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result.used_identifier.kind == "doi"
    assert [attempt["status"] for attempt in result.identifier_attempts] == ["http_404", "success"]
    assert ["pii" if "/pii/" in request.url.path else "doi" for request in requests] == ["pii", "doi"]


def test_canonical_import_records_identifier_fallback_provenance(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found") if "/pii/" in request.url.path else httpx.Response(200, text=ELSEVIER_XML)

    entry, _ = import_identified_item(
        RepositoryPaths.from_root(tmp_path / "literature"),
        LiteratureIdentification(pii="S0000000000000000", doi="10.1000/structured.xml", metadata_source="zotero"),
        publisher=ElsevierApiConfig(api_key="test-key", enabled=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert entry["api_identifier_used_kind"] == "doi"
    assert entry["api_identifier_used_value"] == "10.1000/structured.xml"
    assert [(attempt["kind"], attempt["status"]) for attempt in entry["api_identifier_attempts"]] == [("pii", "http_404"), ("doi", "success")]
    assert entry["api_retrieval_source"] == "elsevier_article_retrieval_api"
    assert entry["pdf_used"] is False


def test_identifier_fallback_missing_key_stops_before_requests() -> None:
    requests = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, text=ELSEVIER_XML)))
    with pytest.raises(MissingApiConfigurationError, match="API key is missing"):
        retrieve_article_via_api_with_identifier_fallback({"pii": "S1234567890123456", "doi": "10.1000/structured.xml"}, ElsevierApiConfig(api_key=None, enabled=True), http_client=client)
    assert requests == []


def test_identifier_fallback_records_unsupported_identifiers_and_clear_failure() -> None:
    with pytest.raises(ArticleApiRetrievalFailed, match="all available identifiers") as caught:
        retrieve_article_via_api_with_identifier_fallback(
            {"ISSN": "1234-5678", "ISBN": "978-1-2345-6789-0", "PMID": "123456"},
            ElsevierApiConfig(api_key="test-key", enabled=True),
        )
    assert [attempt["kind"] for attempt in caught.value.attempts] == ["pmid", "isbn", "issn"]
    assert all(attempt["status"] == "skipped" for attempt in caught.value.attempts)


def test_identifier_fallback_all_supported_attempts_fail_clearly() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404, text="not found")))
    with pytest.raises(ArticleApiRetrievalFailed, match="all available identifiers") as caught:
        retrieve_article_via_api_with_identifier_fallback(
            {"pii": "S0000000000000000", "doi": "10.1000/missing"},
            ElsevierApiConfig(api_key="test-key", enabled=True),
            http_client=client,
        )
    assert [(attempt["kind"], attempt["status"]) for attempt in caught.value.attempts] == [("pii", "http_404"), ("doi", "http_404")]


def test_identified_import_prefers_elsevier_xml_and_does_not_extract_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "fallback.pdf"
    pdf.write_bytes(b"not read")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=ELSEVIER_XML, headers={"Content-Type": "application/xml"})

    def forbidden_pdf_extractor(path: Path) -> str:
        raise AssertionError(f"PDF extractor must not run after XML success: {path}")

    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, duplicate = import_identified_item(
        paths,
        LiteratureIdentification(doi="10.1000/structured.xml", pdf_path=str(pdf), metadata_source="zotero", zotero_key="ABC123"),
        publisher=ElsevierApiConfig(api_key="test-key", enabled=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        pdf_extractor=forbidden_pdf_extractor,
    )
    assert duplicate is False
    assert requests
    assert entry["content_source"] == "elsevier_xml"
    assert entry["extraction_mode"] == "publisher_api_required"
    assert entry["pdf_used"] is False
    assert entry["fallback_used"] is False
    assert entry["xml_retrieved"] is True
    assert entry["metadata_source"] == "zotero+elsevier_xml"
    assert entry["api_retrieval_status"] == "success"
    assert entry["authors"] == ["Ada Curator", "Ben Researcher"]
    assert entry["journal"] == "Journal of Structured Bioprocessing"
    assert entry["year"] == "2026"
    assert "Appendix calibration details." in Path(paths.markdown / f"{entry['canonical_id']}.md").read_text(encoding="utf-8")
    assert (paths.root / entry["xml_artifact_path"]).exists()
    assert entry.get("pdf_fallback_markdown_path") is None


def test_identified_import_uses_pdf_only_after_elsevier_failure(tmp_path: Path) -> None:
    pdf = tmp_path / "fallback.pdf"
    pdf.write_bytes(b"placeholder")
    extracted = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    def pdf_extractor(path: Path) -> str:
        extracted.append(path)
        return "# PDF fallback title\n\nDOI: 10.1000/fallback\n\nFallback evidence."

    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, _ = import_identified_item(
        paths,
        LiteratureIdentification(doi="10.1000/fallback", pdf_path=str(pdf)),
        publisher=ElsevierApiConfig(api_key="test-key", enabled=True),
        extraction_mode="pdf_fallback_allowed",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        pdf_extractor=pdf_extractor,
    )
    assert extracted == [pdf]
    assert entry["content_source"] == "pdf_extraction"
    assert entry["api_retrieval_status"] == "http_503"
    assert any("PDF extraction was used as a fallback" in warning for warning in entry["extraction_warnings"])
    assert entry["pdf_fallback_markdown_path"]
    assert entry["pdf_used"] is True
    assert entry["fallback_used"] is True
    assert entry["fallback_authorized_by"] == "literature_extraction_mode=pdf_fallback_allowed"


def test_strict_api_failure_creates_blocked_metadata_entry_without_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "must-not-be-read.pdf"
    pdf.write_bytes(b"placeholder")
    extracted = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, duplicate = import_identified_item(
        paths,
        LiteratureIdentification(doi="10.1000/blocked", pdf_path=str(pdf)),
        publisher=ElsevierApiConfig(api_key="bad-key", enabled=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        pdf_extractor=lambda path: extracted.append(path) or "forbidden",
    )
    assert extracted == []
    assert duplicate is False
    assert entry["markdown_status"] == "manual_markdown_required"
    assert entry["state"] == "curation_blocked"
    assert entry["markdown_available"] is False
    assert entry["pdf_used"] is False
    assert entry["fallback_used"] is False
    assert Path(paths.root / entry["source_report_path"]).exists()
    assert len(list_entries(paths, ensure=False)) == 1


def test_strict_mode_missing_api_key_stops_before_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "must-not-be-read.pdf"
    pdf.write_bytes(b"placeholder")
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, _ = import_identified_item(paths, LiteratureIdentification(doi="10.1000/missing-key", pdf_path=str(pdf)), publisher=ElsevierApiConfig(api_key=None, enabled=True), pdf_extractor=lambda path: pytest.fail("PDF extractor was called"))
    assert entry["api_retrieval_status"] == "structured_fulltext_unavailable"
    assert entry["markdown_status"] == "manual_markdown_required"
    assert list_entries(paths, ensure=False)[0]["pdf_used"] is False


def test_strict_mode_missing_identifiers_stops_before_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "must-not-be-read.pdf"
    pdf.write_bytes(b"placeholder")
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, _ = import_identified_item(paths, LiteratureIdentification(title="Metadata only item", pdf_path=str(pdf)), publisher=ElsevierApiConfig(api_key="key", enabled=True), pdf_extractor=lambda path: pytest.fail("PDF extractor was called"))
    assert entry["title"] == "Metadata only item"
    assert entry["markdown_status"] == "manual_markdown_required"
    assert entry["pdf_used"] is False


def test_manual_markdown_upload_validates_and_selects_canonical(tmp_path: Path) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, _ = import_identified_item(paths, LiteratureIdentification(title="Manual paper", doi="10.1000/manual"), publisher=ElsevierApiConfig(api_key=None, enabled=True))
    invalid = upload_manual_markdown(paths, entry["canonical_id"], markdown="# Manual paper\n\nToo short.")
    assert invalid["markdown_available"] is False
    assert invalid["validation_errors"]

    valid = upload_manual_markdown(
        paths,
        entry["canonical_id"],
        markdown="# Manual paper\n\nDOI: 10.1000/manual\n\n## Provenance\n\nManual structured Markdown supplied by curator.\n\n## Abstract\n\nThis paper describes a reliable manual literature workflow.\n\n## Methods\n\n" + "Validated structured body text. " * 20,
    )
    assert valid["markdown_available"] is True
    assert valid["markdown_status"] == "markdown_validated"
    assert valid["content_source"] == "manual_markdown"
    assert Path(valid["markdown_file"]).exists()

    fragmented = upload_manual_markdown(
        paths,
        entry["canonical_id"],
        markdown="# Manual paper\n\nDOI: 10.1000/manual\n\n## Abstract\n\n"
        + "\n".join(
            [
                "Manual line one",
                "process line two",
                "curation line three",
                "evidence line four",
                "bioprocess line five",
                "antibody line six",
                "chromatography line seven",
                "quality line eight",
                "measurement line nine",
                "ontology line ten",
                "manual line eleven",
                "process line twelve",
                "curation line thirteen",
                "evidence line fourteen",
                "bioprocess line fifteen",
                "antibody line sixteen",
            ]
        ),
    )
    assert fragmented["markdown_available"] is True
    assert fragmented["markdown_status"] == "manual_markdown_needs_review"
    assert fragmented["state"] == "manual_review_required"
    assert not fragmented["validation_errors"]
    assert "Body text appears to be mostly broken line fragments." in fragmented["validation_warnings"]
    assert Path(fragmented["markdown_file"]).exists()


def test_acs_doi_with_crossref_pdf_link_creates_metadata_only_entry_without_pdf(tmp_path: Path) -> None:
    pdf_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.crossref.org" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "message": {
                        "title": ["ACS structured access test"],
                        "publisher": "American Chemical Society (ACS)",
                        "container-title": ["ACS Journal"],
                        "issued": {"date-parts": [[2026]]},
                        "DOI": "10.1021/acs.example.6b00001",
                        "link": [{"URL": "https://pubs.acs.org/doi/pdf/10.1021/acs.example.6b00001", "content-type": "application/pdf"}],
                    }
                },
            )
        pdf_requests.append(request)
        return httpx.Response(200, text="should not be used")

    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, _ = import_identified_item(
        paths,
        LiteratureIdentification(doi="10.1021/acs.example.6b00001"),
        publisher=ElsevierApiConfig(api_key=None, enabled=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert pdf_requests == []
    assert entry["title"] == "ACS structured access test"
    assert entry["fulltext_status"] == "pdf_available_but_not_used"
    assert entry["markdown_status"] == "manual_markdown_required"
    assert entry["pdf_used"] is False
    assert "No structured ACS full text" in entry["blocked_reason"]


def test_reference_pipeline_xml_shape_has_equivalent_or_better_output() -> None:
    reference_xml = """<article xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:ce="http://www.elsevier.com/xml/common/dtd"><dc:title>Dynamics of batch protein precipitation</dc:title><dc:description>A useful abstract.</dc:description><ce:section><ce:section-title>Introduction</ce:section-title><ce:para>First paragraph.</ce:para><ce:para>Second paragraph.</ce:para></ce:section><ce:section><ce:title>Results</ce:title><ce:para>Important result.</ce:para></ce:section><ce:bib-reference>Smith et al. 2025.</ce:bib-reference></article>"""
    article = parse_elsevier_xml(reference_xml)
    assert article.title == "Dynamics of batch protein precipitation"
    assert article.abstract == "A useful abstract."
    assert article.section_count == 2
    assert article.reference_count == 1
    assert "## Introduction" in article.markdown
    assert "## Results" in article.markdown
    assert "## References" in article.markdown


def test_strict_import_metadata_only_result_is_visible_in_diagnostics_api(client, tmp_path: Path, monkeypatch) -> None:
    project = client.post("/api/projects", json={"name": "Strict diagnostics", "ontology_id": "strict-diag", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": True}).json()
    assert client.post("/api/config/publisher", json={"elsevier_api_key": "bad-key", "publisher_api_enrichment_enabled": True, "literature_extraction_mode": "publisher_api_required"}).status_code == 200
    monkeypatch.setattr(ElsevierArticleClient, "retrieve", lambda self, **kwargs: ElsevierRetrieval("http_403", None, "doi", kwargs.get("doi"), 403))
    imported = client.post("/api/literature/import", json={"project": project["slug"], "doi": "10.1000/blocked"})
    assert imported.status_code == 200
    assert imported.json()["entry"]["markdown_status"] == "manual_markdown_required"
    diagnostics = client.get("/api/literature/import-diagnostics").json()
    assert diagnostics["extraction_mode"] == "publisher_api_required"
    assert diagnostics["last_import"]["api_failures"] == 0
    assert diagnostics["last_import"]["pdf_used"] is False
    assert diagnostics["last_import"]["fallback_used"] is False


def test_pdf_fallback_keeps_zotero_fields_and_fills_missing_metadata_from_crossref(tmp_path: Path) -> None:
    pdf = tmp_path / "fallback.pdf"
    pdf.write_bytes(b"placeholder")

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.crossref.org" in request.url.host:
            return httpx.Response(200, json={"message": {"title": ["Crossref title"], "author": [{"given": "Cross", "family": "Ref"}], "container-title": ["Crossref Journal"], "published-online": {"date-parts": [[2025, 1, 2]]}, "DOI": "10.1000/fallback"}})
        return httpx.Response(404, text="not found")

    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")
    entry, _ = import_identified_item(
        paths,
        LiteratureIdentification(doi="10.1000/fallback", title="Reliable Zotero title", pdf_path=str(pdf), metadata_source="zotero"),
        publisher=ElsevierApiConfig(api_key="test-key", enabled=True),
        extraction_mode="pdf_fallback_allowed",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        pdf_extractor=lambda path: "# Heuristic PDF title\n\nFallback evidence.",
    )
    assert entry["title"] == "Reliable Zotero title"
    assert entry["authors"] == ["Cross Ref"]
    assert entry["journal"] == "Crossref Journal"
    assert entry["year"] == "2025"
    assert entry["metadata_source"] == "zotero+crossref"
    assert entry["crossref_retrieval_status"] == "success"


def test_directory_import_keeps_xml_review_draft_and_saves_lower_priority_pdf_fallback(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input"
    source.mkdir()
    (source / "article.xml").write_text(ELSEVIER_XML, encoding="utf-8")
    (source / "article.pdf").write_bytes(b"placeholder")
    monkeypatch.setattr("backend.app.literature.canonical._pdf_text", lambda path: "# PDF version\n\nDOI: 10.1000/structured.xml\n\nLong PDF fallback text that must not replace XML body evidence.")
    paths = RepositoryPaths.from_root(tmp_path / "project" / "literature")

    result = import_directory(paths, source, source_type="local_folder", extraction_mode="pdf_fallback_allowed")
    entry = list_entries(paths)[0]
    reviewed = Path(entry["markdown_file"]).read_text(encoding="utf-8")

    assert result.failed == 0
    assert entry["content_source"] == "elsevier_xml"
    assert "XML body evidence." in reviewed
    assert "Long PDF fallback text" not in reviewed
    assert "Long PDF fallback text" in (paths.root / entry["pdf_fallback_markdown_path"]).read_text(encoding="utf-8")


def test_staged_review_api_returns_xml_markdown_and_provenance(client, tmp_path: Path, monkeypatch) -> None:
    project = client.post("/api/projects", json={"name": "XML review", "ontology_id": "xml-review", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": True}).json()
    assert client.post("/api/config/publisher", json={"elsevier_api_key": "test-key", "publisher_api_enrichment_enabled": True}).status_code == 200
    monkeypatch.setattr(ElsevierArticleClient, "retrieve", lambda self, **kwargs: ElsevierRetrieval("success", ELSEVIER_XML, "doi", "10.1000/structured.xml"))
    imported = client.post("/api/literature/import", json={"project": project["slug"], "doi": "10.1000/structured.xml", "zotero_key": "ABC123"})
    assert imported.status_code == 200, imported.text
    entry = client.get(f"/api/literature/canonical?project={project['slug']}").json()["staged_entries"][0]
    assert entry["content_source"] == "elsevier_xml"
    assert entry["metadata_source"] == "zotero+elsevier_xml"
    assert "## Appendix A" in entry["literature_markdown"]


def test_publisher_api_test_endpoint_never_uses_pdf_or_creates_staged_entry(client, tmp_path: Path, monkeypatch) -> None:
    project = client.post("/api/projects", json={"name": "API test", "ontology_id": "api-test", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": True}).json()
    assert client.post("/api/config/publisher", json={"elsevier_api_key": "test-key", "publisher_api_enrichment_enabled": True}).status_code == 200
    monkeypatch.setattr(ElsevierArticleClient, "retrieve", lambda self, **kwargs: ElsevierRetrieval("success", ELSEVIER_XML, "pii", kwargs.get("pii"), 200, "text/xml", "https://api.elsevier.test"))
    tested = client.post("/api/literature/test-publisher-api", json={"project": project["slug"], "pii": "S1234567890123456"})
    assert tested.status_code == 200, tested.text
    assert tested.json()["xml_retrieved"] is True
    assert tested.json()["pdf_used"] is False
    assert tested.json()["section_count"] >= 2
    assert Path(tested.json()["markdown_path"]).exists()
    assert client.get(f"/api/literature/canonical?project={project['slug']}").json()["staged_entries"] == []


def test_zotero_storage_import_uses_synced_identifiers_for_xml_before_pdf(client, tmp_path: Path, monkeypatch) -> None:
    project = client.post("/api/projects", json={"name": "Zotero XML priority", "ontology_id": "zotero-xml", "project_type": "domain_ontology", "local_workspace_path": str(tmp_path), "activate": True}).json()
    storage = tmp_path / "zotero-storage"
    storage.mkdir()
    (storage / "fallback.pdf").write_bytes(b"placeholder")
    with db_session.SessionLocal() as session:
        session.add(LiteratureSource(provider="zotero", provider_item_key="XMLFIRST", title="Reliable Zotero title", normalized_title="reliable zotero title", creators_json="[]", doi="10.1000/structured.xml", normalized_doi="10.1000/structured.xml"))
        session.commit()
    assert client.post("/api/config/publisher", json={"elsevier_api_key": "test-key", "publisher_api_enrichment_enabled": True}).status_code == 200
    monkeypatch.setattr(ElsevierArticleClient, "retrieve", lambda self, **kwargs: ElsevierRetrieval("success", ELSEVIER_XML, "doi", kwargs.get("doi")))
    monkeypatch.setattr("backend.app.literature.canonical._pdf_text", lambda path: (_ for _ in ()).throw(AssertionError("PDF extraction must not run in strict mode")))

    imported = client.post("/api/literature/import", json={"project": project["slug"], "zotero_storage": str(storage)})
    assert imported.status_code == 200, imported.text
    assert imported.json()["xml_imported"] == 1
    entry = client.get(f"/api/literature/canonical?project={project['slug']}").json()["staged_entries"][0]
    assert entry["content_source"] == "elsevier_xml"
    assert "XML body evidence." in entry["literature_markdown"]
    assert "PDF fallback must not win" not in entry["literature_markdown"]
    assert entry["pdf_fallback_markdown_path"] is None
    assert entry["pdf_used"] is False
    assert entry["fallback_used"] is False


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
    imported = client.post("/api/literature/import", json={"project": created.json()["slug"], "pdf_dir": str(source), "extraction_mode": "pdf_only"})
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
    assert client.post("/api/literature/import", json={"project": project["slug"], "pdf_dir": str(source), "extraction_mode": "pdf_only"}).status_code == 200
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
    assert publisher["enable_publisher_api_enrichment"] is True
    assert publisher["literature_extraction_mode"] == "publisher_api_required"
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
    result = import_directory(paths, source, source_type="zotero_storage", extraction_mode="pdf_only")
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
    result = CliRunner().invoke(cli_app, ["literature", "import", "--project", "cli", "--pdf-dir", str(source), "--extraction-mode", "pdf_only"])
    assert result.exit_code == 0, result.output
    assert "imported 1" in result.output
    assert len(list_entries(paths)) == 1


def test_publisher_api_test_cli_reports_xml_and_never_needs_pdf(tmp_path: Path, monkeypatch) -> None:
    paths = RepositoryPaths.from_root(tmp_path / "projects" / "cli" / "literature")
    fake_session = SimpleNamespace(close=lambda: None)
    publisher = SimpleNamespace(api_key="test-key", inst_token=None, base_url="https://api.elsevier.test", enabled=True)
    monkeypatch.setattr("backend.app.cli._literature_project_paths", lambda project: (fake_session, SimpleNamespace(slug=project), paths))
    monkeypatch.setattr("backend.app.services.runtime_config.publisher_config", lambda session: publisher)
    monkeypatch.setattr(
        "backend.app.literature.canonical.test_publisher_api",
        lambda *args, **kwargs: {
            "api_provider": "elsevier",
            "request_status": "success",
            "title": "Structured Protein Recovery",
            "authors": ["Ada Curator"],
            "journal": "Journal of Structured Bioprocessing",
            "year": "2026",
            "doi": "10.1000/structured.xml",
            "pii": "S1234567890123456",
            "section_count": 2,
            "xml_retrieved": True,
            "pdf_used": False,
            "markdown_path": None,
        },
    )

    result = CliRunner().invoke(cli_app, ["literature", "test-api", "--project", "cli", "--pii", "S1234567890123456", "--no-write-artifacts"])

    assert result.exit_code == 0, result.output
    assert '"api_provider": "elsevier"' in result.output
    assert '"xml_retrieved": true' in result.output
    assert '"pdf_used": false' in result.output
    assert list_entries(paths, ensure=False) == []
