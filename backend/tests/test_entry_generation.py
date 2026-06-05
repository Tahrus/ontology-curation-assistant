import json
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.config import get_settings
from backend.app.db import session as db_session
from backend.app.extraction.parser import parse_candidate_response
from backend.app.extraction.service import persist_candidates
from backend.app.github_export import GitHubExportConfig, save_generated_ontology_to_github
from backend.app.literature.exporter import refresh_literature_markdown_repository
from backend.app.literature.pipeline import (
    LiteraturePipelineConfig,
    combine_markdown_files,
    discover_zotero_pdfs,
    literature_pipeline_config_from_settings,
    run_literature_pipeline,
    validate_pipeline_config,
)
from backend.app.literature.repository import (
    clean_extracted_text,
    combine_literature_markdown,
    display_literature_markdown,
    extract_llm_ready_paper,
    literature_context_for_entry_generation,
    load_literature_markdown,
    load_llm_ready_repository,
    load_llm_ready_repository_with_diagnostics,
    reset_literature_repository,
    save_literature_markdown,
    write_extracted_paper,
)
from backend.app.llm.ontology_suggestions import (
    run_ontology_suggestion_test,
    validate_ontology_suggestion_payload,
)
from backend.app.models.db import CandidateTermRecord, LiteratureDocument
from backend.app.odk.integration import stage_generated_ontology_artifact
from backend.app.services.runtime_config import LlmRuntimeConfig


def test_reset_literature_repository_when_files_exist(tmp_path):
    repository = tmp_path / "literature" / "papers"
    repository.mkdir(parents=True)
    (repository / "paper.md").write_text("# Paper", encoding="utf-8")

    result = reset_literature_repository(repository)

    assert result.ok
    assert result.deleted
    assert repository.exists()
    assert list(repository.iterdir()) == []


def test_reset_literature_repository_deletes_existing_json_and_nested_files(tmp_path):
    repository = tmp_path / "literature" / "papers"
    nested = repository / "nested"
    nested.mkdir(parents=True)
    (repository / "paper.md").write_text("# Paper", encoding="utf-8")
    (nested / "nested-paper.md").write_text("# Nested paper", encoding="utf-8")
    (nested / "notes.txt").write_text("notes", encoding="utf-8")

    result = reset_literature_repository(repository)

    assert result.ok
    assert repository.exists()
    assert not (repository / "paper.md").exists()
    assert not nested.exists()
    assert any("nested-paper.md" in path for path in result.deleted)


def test_reset_literature_repository_when_empty(tmp_path):
    repository = tmp_path / "literature" / "papers"
    repository.mkdir(parents=True)

    result = reset_literature_repository(repository)

    assert result.ok
    assert result.deleted == []
    assert repository.exists()


def test_reset_literature_repository_when_path_missing(tmp_path):
    repository = tmp_path / "missing" / "papers"

    result = reset_literature_repository(repository)

    assert result.ok
    assert repository.exists()
    assert result.deleted == []
    assert repository.is_dir()


def test_reset_literature_repository_keeps_unrelated_ontology_output(tmp_path):
    repository = tmp_path / "literature" / "papers"
    ontology_output = tmp_path / "ontology-output" / "generated.owl"
    repository.mkdir(parents=True)
    ontology_output.parent.mkdir(parents=True)
    (repository / "paper.md").write_text("# Paper", encoding="utf-8")
    ontology_output.write_text("ontology", encoding="utf-8")

    reset_literature_repository(repository)

    assert ontology_output.read_text(encoding="utf-8") == "ontology"


def test_reset_literature_repository_default_clears_entire_literature_base(tmp_path, monkeypatch):
    base = tmp_path / "literature"
    monkeypatch.setenv("OCA_LITERATURE_BASE_DIR", str(base))
    monkeypatch.setenv("OCA_LITERATURE_REPOSITORY_PATH", str(base / "papers"))
    get_settings.cache_clear()
    for folder, filename in [
        ("Paper-PDF", "paper.pdf"),
        ("Markdown", "paper.md"),
        ("papers", "entry.md"),
    ]:
        target = base / folder
        target.mkdir(parents=True)
        (target / filename).write_text("content", encoding="utf-8")
    (base / "combined_literature.md").write_text("# Combined", encoding="utf-8")
    (base / "literature.json").write_text("{}", encoding="utf-8")

    result = reset_literature_repository()

    assert result.ok
    assert result.path == base
    assert base.exists()
    assert list(base.iterdir()) == []
    assert any("literature.json" in item for item in result.deleted)
    get_settings.cache_clear()


def test_load_literature_repository_skips_malformed_markdown_when_valid_files_exist(tmp_path):
    valid = tmp_path / "valid.md"
    malformed = tmp_path / "bad.md"
    nested = tmp_path / "nested"
    nested.mkdir()
    save_literature_markdown(
        {
            "id": "protein-paper",
            "title": "Protein paper",
            "doi": "10.1/example",
            "citation": {"lead_author_year": "Smith, 2026"},
            "abstract": "Abstract",
            "sections": [{"heading": "Introduction", "text": "Useful text.", "subsections": []}],
        },
        tmp_path,
    ).replace(valid)
    malformed.write_text("# Missing front matter", encoding="utf-8")
    (nested / "invalid-shape.md").write_text("# Also missing front matter", encoding="utf-8")

    result = load_llm_ready_repository_with_diagnostics(tmp_path)
    context, context_result = literature_context_for_entry_generation(tmp_path)

    assert [paper["title"] for paper in result.papers] == ["Protein paper"]
    assert len(result.skipped_files) == 2
    assert context_result.skipped_files
    assert "Protein paper" in context
    assert "10.1/example" in context
    assert "# Literature Corpus" in context


def test_literature_repository_context_empty_repository_is_controlled(tmp_path):
    context, result = literature_context_for_entry_generation(tmp_path)

    assert context == ""
    assert result.papers == []
    assert result.skipped_files == []


def test_extract_llm_ready_paper_cleans_pdf_artifacts_and_sections():
    raw_text = """
Protein Recovery Assays
Smith, Jane and Lee, Kai
2024
doi: 10.1234/example.doi
Downloaded from publisher
1
Abstract
Recovery of a bio-
pharmaceutical protein is monitored.
1 Introduction
Protein recovery preserves domain-specific assay terminology.
1.1 Batch processing and monitoring solutions
Despite the inherent variability, monitoring solutions track recovery.
References
Smith J. 2020. Irrelevant citation.
"""

    paper = extract_llm_ready_paper(raw_text)

    assert paper["title"] == "Protein Recovery Assays"
    assert paper["doi"] == "10.1234/example.doi"
    assert paper["citation"]["lead_author_year"] == "Smith, 2024"
    assert "biopharmaceutical" in paper["abstract"]
    assert paper["sections"][0]["heading"] == "Introduction"
    assert paper["sections"][0]["subsections"][0]["heading"] == "Batch processing and monitoring solutions"
    assert "Irrelevant citation" not in json.dumps(paper)
    assert "Downloaded from publisher" not in clean_extracted_text(raw_text)


def test_write_extracted_paper_uses_stable_safe_filename(tmp_path):
    path = write_extracted_paper(
        "Title\nAuthor, Alice\n2025\nAbstract\nUseful ontology text.",
        tmp_path,
        doi="10.9999/ABC DEF",
    )

    assert path.parent == tmp_path
    assert path.suffix == ".md"
    assert "10-9999-abc-def" in path.name
    assert "## Abstract" in path.read_text(encoding="utf-8")


def test_literature_markdown_round_trip_and_combined_corpus(tmp_path):
    paper = {
        "id": "literature-id",
        "title": "Article title",
        "authors": ["Author One", "Author Two"],
        "year": 2024,
        "doi": "10.xxxx/example",
        "abstract": "Abstract text.",
        "sections": [{"heading": "Introduction", "text": "Ontology-relevant text.", "subsections": []}],
    }

    path = save_literature_markdown(paper, tmp_path)
    loaded = load_literature_markdown(path)
    corpus = combine_literature_markdown([loaded])

    assert path.name.endswith(".md")
    assert loaded["metadata"]["authors"] == ["Author One", "Author Two"]
    assert loaded["abstract"] == "Abstract text."
    assert "## Literature Entry: literature-id" in corpus
    assert f"Source file: `{path.name}`" in corpus
    assert display_literature_markdown(loaded).startswith("---")


def test_literature_pipeline_config_uses_configured_zotero_storage(tmp_path, monkeypatch):
    storage = tmp_path / "custom-storage"
    monkeypatch.setenv("OCA_ZOTERO_LITERATURE_STORAGE_PATH", str(storage))
    monkeypatch.setenv("OCA_LITERATURE_BASE_DIR", str(tmp_path / "literature"))
    monkeypatch.setenv("OCA_LITERATURE_PDF_DIR", str(tmp_path / "literature" / "pdfs"))
    monkeypatch.setenv("OCA_LITERATURE_GENERATED_MD_DIR", str(tmp_path / "literature" / "generated"))
    monkeypatch.setenv("OCA_LITERATURE_REPOSITORY_PATH", str(tmp_path / "literature" / "papers"))
    monkeypatch.setenv(
        "OCA_LITERATURE_COMBINED_OUTPUT_FILE",
        str(tmp_path / "literature" / "combined.md"),
    )
    get_settings.cache_clear()

    config = literature_pipeline_config_from_settings()

    assert config.zotero_literature_storage_path == storage
    assert "Zotero\\storage" not in str(config.zotero_literature_storage_path)
    assert config.combined_output_file == tmp_path / "literature" / "combined.md"
    get_settings.cache_clear()


def test_literature_pipeline_accepts_windows_zotero_storage_path(monkeypatch):
    storage = Path(r"C:\Users\ge47vob\Zotero\storage")
    monkeypatch.setenv("OCA_ZOTERO_LITERATURE_STORAGE_PATH", str(storage))
    get_settings.cache_clear()

    config = literature_pipeline_config_from_settings()

    assert config.zotero_literature_storage_path == storage
    assert str(config.zotero_literature_storage_path) == r"C:\Users\ge47vob\Zotero\storage"
    get_settings.cache_clear()


def test_literature_pipeline_missing_zotero_storage_is_clear(tmp_path):
    config = LiteraturePipelineConfig(
        zotero_literature_storage_path=tmp_path / "missing-storage",
        base_dir=tmp_path / "literature",
        pdf_dir=tmp_path / "literature" / "Paper-PDF",
        generated_md_dir=tmp_path / "literature" / "Markdown",
        papers_dir=tmp_path / "literature" / "papers",
        combined_output_file=tmp_path / "literature" / "combined_literature.md",
    )

    try:
        validate_pipeline_config(config)
    except FileNotFoundError as exc:
        assert "Configured Zotero literature storage path was not found" in str(exc)
    else:
        raise AssertionError("missing Zotero storage should raise FileNotFoundError")


def test_literature_pipeline_empty_zotero_storage_is_clear(tmp_path):
    storage = tmp_path / "zotero-storage"
    storage.mkdir()
    config = LiteraturePipelineConfig(
        zotero_literature_storage_path=storage,
        base_dir=tmp_path / "literature",
        pdf_dir=tmp_path / "literature" / "Paper-PDF",
        generated_md_dir=tmp_path / "literature" / "Markdown",
        papers_dir=tmp_path / "literature" / "papers",
        combined_output_file=tmp_path / "literature" / "combined_literature.md",
    )

    try:
        run_literature_pipeline(config)
    except ValueError as exc:
        assert "No PDF files were found under the configured Zotero literature storage path" in str(exc)
    else:
        raise AssertionError("empty Zotero storage should raise a clear ValueError")


def test_literature_pipeline_copies_pdfs_generates_markdown_and_combined_corpus(tmp_path):
    import fitz  # type: ignore[import-untyped]

    storage = tmp_path / "zotero-storage" / "ATTACHMENT1"
    storage.mkdir(parents=True)
    pdf_path = storage / "Protein Recovery.PDF"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Protein Recovery Assays\nAbstract\nPreferential hydration stabilizes proteins.\n1. Introduction\nUseful ontology text.",
    )
    document.save(pdf_path)
    document.close()

    config = LiteraturePipelineConfig(
        zotero_literature_storage_path=tmp_path / "zotero-storage",
        base_dir=tmp_path / "literature",
        pdf_dir=tmp_path / "literature" / "Paper-PDF",
        generated_md_dir=tmp_path / "literature" / "Markdown",
        papers_dir=tmp_path / "literature" / "papers",
        combined_output_file=tmp_path / "literature" / "combined_literature.md",
    )

    result = run_literature_pipeline(config)

    copied_pdfs = list(config.pdf_dir.glob("*.pdf"))
    copied_upper_pdfs = list(config.pdf_dir.glob("*.PDF"))
    generated_markdown = list(config.generated_md_dir.glob("*.md"))
    paper_markdown = list(config.papers_dir.glob("*.md"))
    combined_text = result.combined_output_file.read_text(encoding="utf-8")

    assert discover_zotero_pdfs(tmp_path / "zotero-storage") == [pdf_path]
    assert result.copied_pdf_count == 1
    assert result.converted_markdown_count == 1
    assert (copied_pdfs or copied_upper_pdfs)[0].name == "Protein Recovery.PDF"
    assert generated_markdown
    assert paper_markdown
    assert 'source: "Zotero literature pipeline"' in paper_markdown[0].read_text(encoding="utf-8")
    assert "# Combined Literature Markdown" in combined_text
    assert "Protein Recovery" in combined_text
    assert result.combined_markdown_count == 1
    assert not (tmp_path / "literature" / "literature.json").exists()


def test_literature_pipeline_repeated_run_does_not_duplicate_pdf_or_markdown_artifacts(tmp_path):
    import fitz  # type: ignore[import-untyped]

    storage = tmp_path / "zotero-storage" / "ATTACHMENT1"
    storage.mkdir(parents=True)
    pdf_path = storage / "Protein Recovery.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Protein Recovery Assays\nAbstract\nPreferential hydration stabilizes proteins.\n1. Introduction\nUseful ontology text.",
    )
    document.save(pdf_path)
    document.close()

    config = LiteraturePipelineConfig(
        zotero_literature_storage_path=tmp_path / "zotero-storage",
        base_dir=tmp_path / "literature",
        pdf_dir=tmp_path / "literature" / "Paper-PDF",
        generated_md_dir=tmp_path / "literature" / "Markdown",
        papers_dir=tmp_path / "literature" / "papers",
        combined_output_file=tmp_path / "literature" / "combined_literature.md",
    )

    first = run_literature_pipeline(config)
    second = run_literature_pipeline(config)

    assert first.copied_pdf_count == 1
    assert second.copied_pdf_count == 1
    assert len(list(config.pdf_dir.glob("*.pdf"))) == 1
    assert len(list(config.generated_md_dir.glob("*.md"))) == 1
    assert len(list(config.papers_dir.glob("*.md"))) == 1
    assert "_1" not in " ".join(path.name for path in config.pdf_dir.iterdir())
    assert "# Combined Literature Markdown" in config.combined_output_file.read_text(encoding="utf-8")
    assert not (tmp_path / "literature" / "literature.json").exists()


def test_llm_ontology_suggestion_dry_run_exports_trace_from_markdown_repository(tmp_path):
    save_literature_markdown(
        {
            "id": "lit-1",
            "title": "Protein recovery paper",
            "authors": ["Curator One"],
            "year": 2026,
            "doi": "10.1000/recovery",
            "abstract": "Protein recovery is measured.",
            "sections": [{"heading": "Introduction", "text": "Preferential hydration is relevant.", "subsections": []}],
        },
        tmp_path / "papers",
    )

    output = tmp_path / "suggestions" / "trace.json"
    result = run_ontology_suggestion_test(
        config=LlmRuntimeConfig(provider=None, api_key=None, model=None, base_url=None),
        repository_path=tmp_path / "papers",
        output_path=output,
        dry_run=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert result.ok
    assert result.dry_run
    assert result.literature_count == 1
    assert payload["payload"] == {"suggestions": []}
    assert "Protein recovery paper" in payload["prompt"]
    assert "10.1000/recovery" in payload["prompt"]
    validate_ontology_suggestion_payload(
        {
            "suggestions": [
                {
                    "proposed_label": "preferential hydration",
                    "definition": "A protein solvent interaction.",
                    "synonyms": [],
                    "parent_class": None,
                    "source_literature_ids": ["lit-1"],
                    "confidence": 0.8,
                    "rationale": "Supported by text.",
                }
            ]
        }
    )


def test_combine_markdown_files_writes_combined_literature_markdown(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "alpha.md").write_text("# Alpha\n\nUseful text.", encoding="utf-8")
    (papers / "beta.md").write_text("# Beta\n\nMore text.", encoding="utf-8")
    output = tmp_path / "combined_literature.md"

    count = combine_markdown_files(papers, output)

    text = output.read_text(encoding="utf-8")
    assert count == 2
    assert "# Combined Literature Markdown" in text
    assert "Source folder:" in text
    assert "Number of files: 2" in text
    assert "<!-- Source file: alpha.md -->" in text
    assert "---" in text


def test_save_generated_ontology_to_github_creates_file():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"message": "not found"})
        assert request.method == "PUT"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["message"] == "Add generated PPO candidate"
        assert payload["branch"] == "curation-test"
        return httpx.Response(
            201,
            json={"commit": {"html_url": "https://github.example/commit/abc"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = save_generated_ontology_to_github(
        {"templates/generated.tsv": "ID\tLABEL\nTEMP:1\tpreferential hydration\n"},
        commit_message="Add generated PPO candidate",
        config=GitHubExportConfig(
            token="token",
            repository="owner/repo",
            branch="curation-test",
            base_path="src/ontology",
            api_base_url="https://api.github.test",
        ),
        client=client,
    )

    assert result.ok
    assert result.commit_url == "https://github.example/commit/abc"
    assert requests[-1].url.path == "/repos/owner/repo/contents/src/ontology/templates/generated.tsv"


def test_save_generated_ontology_to_github_missing_auth_is_clear():
    result = save_generated_ontology_to_github(
        {"file.owl": "content"},
        commit_message="Save",
        config=GitHubExportConfig(token=None, repository="owner/repo", branch="main"),
    )

    assert not result.ok
    assert "GITHUB_TOKEN" in result.message


def test_entry_generation_workflow(tmp_path, monkeypatch):
    database_path = tmp_path / "test.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", session_factory)
    monkeypatch.setenv("OCA_LITERATURE_REPOSITORY_PATH", str(tmp_path / "literature" / "papers"))
    get_settings.cache_clear()
    db_session.Base.metadata.create_all(bind=engine)

    reset = reset_literature_repository(get_settings().literature_repository_path)
    assert reset.ok

    source_path = tmp_path / "sample-paper.txt"
    source_path.write_text(
        "Protein Solvent Preferential Interactions\n"
        "Nguyen, Ana\n"
        "2026\n"
        "Abstract\nPreferential hydration describes protein-solvent enrichment.\n"
        "Introduction\nPreferential hydration stabilizes proteins in solution.\n",
        encoding="utf-8",
    )

    with session_factory() as session:
        document = LiteratureDocument.from_path(source_path)
        session.add(document)
        session.commit()
        markdown_paths = refresh_literature_markdown_repository(session, get_settings().literature_repository_path)
        assert markdown_paths
        assert not (tmp_path / "literature" / "literature.json").exists()
        document_id = document.id

    papers = load_llm_ready_repository(get_settings().literature_repository_path)
    assert papers[0]["title"] == "sample-paper.txt"
    assert papers[0]["sections"]
    assert Path(papers[0]["source_file"]).suffix == ".md"

    response = parse_candidate_response(
        json.dumps(
            {
                "candidates": [
                    {
                        "label": "preferential hydration",
                        "proposed_definition": "Protein-solvent enrichment around a protein.",
                        "confidence_score": 0.91,
                        "evidence": [
                            {
                                "quoted_text": "Preferential hydration stabilizes proteins in solution.",
                                "direct_or_inferred": "direct",
                            }
                        ],
                    }
                ]
            }
        )
    )
    with session_factory() as session:
        inserted, skipped = persist_candidates(
            session,
            document_id=document_id,
            response=response,
            provider="mock",
            model="fixture",
            raw_response="{}",
        )
        candidate = session.scalar(select(CandidateTermRecord))

    assert inserted == 1
    assert skipped == 0
    assert candidate.label == "preferential hydration"
    assert candidate.proposed_definition

    ppo_path = tmp_path / "ppo" / "src" / "ontology"
    ppo_path.mkdir(parents=True)
    staged = stage_generated_ontology_artifact(
        "templates/ai_generated_terms.tsv",
        f"ID\tLABEL\tdefinition\n{candidate.candidate_id}\t{candidate.label}\t{candidate.proposed_definition}\n",
        ontology_path=ppo_path,
    )
    assert staged.exists()
    assert "preferential hydration" in staged.read_text(encoding="utf-8")

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                404,
                json={"message": "not found"},
            )
            if request.method == "GET"
            else httpx.Response(201, json={"commit": {"html_url": "https://github.example/commit/entry"}})
        )
    )
    github = save_generated_ontology_to_github(
        {"templates/ai_generated_terms.tsv": staged},
        commit_message="Add generated ontology entry",
        config=GitHubExportConfig(
            token="token",
            repository="owner/repo",
            branch="entry-test",
            api_base_url="https://api.github.test",
        ),
        client=client,
    )

    assert github.ok
    assert github.commit_url == "https://github.example/commit/entry"
    get_settings.cache_clear()
