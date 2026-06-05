import pytest

from zotero_lit_md import cli
from zotero_lit_md.chunking import build_retrieval_chunks
from zotero_lit_md.local_pdf import (
    ExtractedPage,
    ExtractedPdf,
    build_local_retrieval_chunks,
    convert_headings,
    extract_pdf_text,
    find_pdfs,
    sanitize_pdf_stem,
    write_extracted_pdf_markdown,
)
from zotero_lit_md.pdf_extractor import parse_sections_from_pages
from zotero_lit_md.schema import PageText, SectionBlock
from zotero_lit_md.text_cleaning import (
    detect_heading_level,
    paper_markdown_filename,
    remove_repeating_headers_footers,
)
from zotero_lit_md.zotero_client import find_pdf_for_attachment_key, find_pdfs_for_attachment_key, is_pdf_attachment, resolve_attachment_pdf_path


def test_heading_detection_numbered_and_canonical():
    assert detect_heading_level("1. Introduction") == 2
    assert detect_heading_level("1.1. Background") == 3
    assert detect_heading_level("1.1.1 Model details") == 4
    assert detect_heading_level("References") == 2
    assert detect_heading_level("Figure 2. Caption text") == 3


def test_local_pdf_recursive_and_nonrecursive_discovery(tmp_path):
    root_pdf = tmp_path / "root.pdf"
    child_pdf = tmp_path / "nested" / "child.PDF"
    child_pdf.parent.mkdir()
    root_pdf.write_bytes(b"%PDF root")
    child_pdf.write_bytes(b"%PDF child")

    assert find_pdfs(tmp_path, recursive=False) == [root_pdf]
    assert set(find_pdfs(tmp_path, recursive=True)) == {root_pdf, child_pdf}


def test_local_pdf_filename_sanitization():
    assert sanitize_pdf_stem('bad<name>:"/\\|?*') == "bad_name_"


def test_local_pdf_extraction_status_assignment(tmp_path):
    pdf = tmp_path / "short.pdf"
    _write_minimal_pdf(pdf, text="short")

    extracted = extract_pdf_text(pdf)

    assert extracted.extraction_method == "PyMuPDF"
    assert extracted.extraction_status == "partial_or_empty"
    assert extracted.total_char_count < 500


def test_local_markdown_writing_from_fake_extracted_text(tmp_path):
    extracted = ExtractedPdf(
        pdf_path=tmp_path / "paper.pdf",
        pdf_filename="paper.pdf",
        page_count=1,
        pages=[ExtractedPage(1, "Abstract\nProtein precipitation text.\nReferences\nA citation.", 58)],
        total_char_count=58,
        extraction_method="PyMuPDF",
        extraction_status="partial_or_empty",
        warnings=["fixture warning"],
    )

    path = write_extracted_pdf_markdown(extracted, tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "## LLM-ready full-text Markdown" in text
    assert "- **Source:** local PDF" in text
    assert "Protein precipitation text." in text


def test_folder_to_md_no_pdfs_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["folder-to-md", "--folder", str(tmp_path), "--output", str(tmp_path / "out"), "--recursive"])

    assert "No PDFs found in:" in str(exc.value)


def test_local_heading_and_caption_conversion():
    converted = convert_headings(
        "\n".join(
            [
                "1. Introduction",
                "Intro text.",
                "1.1. Batch processing and monitoring solutions",
                "Fig. 1. Overview of the workflow",
                "Table 1 An overview of PBM parameters",
                "References",
            ]
        )
    )

    assert "## 1. Introduction" in converted
    assert "### 1.1. Batch processing and monitoring solutions" in converted
    assert "### Figure 1\n\nOverview of the workflow" in converted
    assert "### Table 1\n\nAn overview of PBM parameters" in converted
    assert "## References" in converted


def test_local_retrieval_chunk_generation(tmp_path):
    text = "\n\n".join(["Methods\nProtein precipitation model parameters and lysozyme concentration."] * 80)
    extracted = ExtractedPdf(
        pdf_path=tmp_path / "paper.pdf",
        pdf_filename="paper.pdf",
        page_count=1,
        pages=[ExtractedPage(1, text, len(text))],
        total_char_count=len(text),
        extraction_method="PyMuPDF",
        extraction_status="complete",
    )

    chunks = build_local_retrieval_chunks(extracted, target_tokens=100, max_tokens=160)

    assert len(chunks) > 1
    assert all(chunk["approx_tokens"] <= 180 for chunk in chunks)
    assert any("Protein" in chunk["key_terms"] for chunk in chunks)


def test_local_output_filename_collision_behavior(tmp_path):
    extracted = ExtractedPdf(
        pdf_path=tmp_path / "paper.pdf",
        pdf_filename="paper.pdf",
        page_count=1,
        pages=[ExtractedPage(1, "Protein text " * 60, 780)],
        total_char_count=780,
        extraction_method="PyMuPDF",
        extraction_status="complete",
    )

    first = write_extracted_pdf_markdown(extracted, tmp_path)
    second = write_extracted_pdf_markdown(extracted, tmp_path)

    assert first.name == "paper.md"
    assert second.name == "paper_2.md"


def test_pdf_to_md_command_processes_one_pdf(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _write_minimal_pdf(pdf)
    output = tmp_path / "out"

    cli.main(["pdf-to-md", "--pdf", str(pdf), "--output", str(output), "--verbose"])

    markdown_files = list(output.glob("*.md"))
    assert len(markdown_files) == 1
    assert "## Paper body" in markdown_files[0].read_text(encoding="utf-8")


def test_folder_to_md_command_processes_recursive_pdfs(tmp_path):
    first = tmp_path / "storage" / "A" / "one.pdf"
    second = tmp_path / "storage" / "B" / "two.PDF"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    _write_minimal_pdf(first)
    _write_minimal_pdf(second)
    output = tmp_path / "out-folder"

    cli.main(["folder-to-md", "--folder", str(tmp_path / "storage"), "--output", str(output), "--recursive"])

    assert len(list(output.glob("*.md"))) == 2


def test_header_footer_removal_preserves_body_text():
    pages = [
        "Journal Header\n1\nIntroduction\nImportant α-protein text.\nJournal Footer",
        "Journal Header\n2\nResults\nMore β-sheet text.\nJournal Footer",
    ]

    cleaned = remove_repeating_headers_footers(pages)

    assert "Journal Header" not in "\n".join(cleaned)
    assert "Journal Footer" not in "\n".join(cleaned)
    assert "Important α-protein text." in cleaned[0]
    assert "More β-sheet text." in cleaned[1]


def test_chunk_size_behavior_prefers_paragraph_boundaries():
    section = SectionBlock(
        heading="Results",
        page_start=2,
        page_end=3,
        text="\n\n".join(["preferential hydration stabilizes proteins in solution."] * 220),
    )

    chunks = build_retrieval_chunks([section], paper_key="PAPER", target_tokens=80, max_tokens=120)

    assert len(chunks) > 1
    assert all(chunk.approx_tokens <= 140 for chunk in chunks)
    assert all(chunk.heading_path == ["Results"] for chunk in chunks)


def test_filename_sanitization_and_collision_key():
    existing = {"2026_smith_protein-solvent-effects.md"}

    filename = paper_markdown_filename(
        year="2026",
        lead_author="Smith",
        title="Protein/Solvent Effects!",
        zotero_key="ABCD1234",
        existing=existing,
    )

    assert filename == "2026_smith_protein-solvent-effects_abcd1234.md"


def test_zotero_attachment_filtering():
    assert is_pdf_attachment({"data": {"itemType": "attachment", "contentType": "application/pdf"}})
    assert is_pdf_attachment({"data": {"itemType": "attachment", "filename": "paper.PDF"}})
    assert is_pdf_attachment({"data": {"itemType": "attachment", "title": "Best available PDF"}})
    assert not is_pdf_attachment({"data": {"itemType": "note", "contentType": "application/pdf"}})
    assert not is_pdf_attachment({"data": {"itemType": "attachment", "filename": "notes.txt"}})


def test_parse_sections_from_pages_preserves_page_ranges():
    sections = parse_sections_from_pages(
        [
            PageText(1, "1 Introduction\nIntro text."),
            PageText(2, "1.1 Background\nBackground text.\nReferences\nReference text."),
        ]
    )

    intro = next(section for section in sections if section.heading == "1 Introduction")
    assert intro.page_start == 1
    assert intro.subsections[0].heading == "1.1 Background"
    assert any(section.heading == "References" for section in sections)


def test_storage_pdf_path_resolution(tmp_path):
    pdf = tmp_path / "storage" / "ATTACH1" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF fixture")
    attachment = {"key": "ATTACH1", "data": {"itemType": "attachment", "path": "storage:paper.pdf"}}

    resolved = resolve_attachment_pdf_path(attachment, tmp_path)

    assert resolved == pdf


def test_find_pdf_for_attachment_key_single_pdf(tmp_path):
    pdf = tmp_path / "storage" / "ATTACH1" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF fixture")

    assert find_pdf_for_attachment_key(tmp_path, "ATTACH1") == [pdf.resolve()]


def test_find_pdfs_for_attachment_key_uses_storage_path_directly(tmp_path):
    storage = tmp_path / "storage"
    pdf = storage / "ATTACHDIRECT" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF fixture")

    assert find_pdfs_for_attachment_key(storage, "ATTACHDIRECT") == [pdf.resolve()]


def test_find_pdf_for_attachment_key_exact_filename_match(tmp_path):
    storage = tmp_path / "storage" / "ATTACHMETA"
    storage.mkdir(parents=True)
    first = storage / "other.pdf"
    second = storage / "exact.pdf"
    first.write_bytes(b"%PDF other")
    second.write_bytes(b"%PDF exact")

    found = find_pdf_for_attachment_key(
        tmp_path,
        "ATTACHMETA",
        {"data": {"filename": "exact.pdf", "title": "Other PDF"}},
    )

    assert found[0] == second.resolve()


def test_find_pdf_for_attachment_key_storage_path_hint(tmp_path):
    storage = tmp_path / "storage" / "ATTACHPATH"
    storage.mkdir(parents=True)
    first = storage / "alpha.pdf"
    second = storage / "hinted.pdf"
    first.write_bytes(b"%PDF alpha")
    second.write_bytes(b"%PDF hinted")

    found = find_pdf_for_attachment_key(
        tmp_path,
        "ATTACHPATH",
        {"data": {"path": "storage:hinted.pdf"}},
    )

    assert found[0] == second.resolve()


def test_find_pdf_for_attachment_key_recursive_pdf(tmp_path):
    pdf = tmp_path / "storage" / "ATTACHRECURSE" / "subfolder" / "paper.PDF"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF fixture")

    assert find_pdf_for_attachment_key(tmp_path, "ATTACHRECURSE") == [pdf.resolve()]


def test_absolute_linked_pdf_path_resolution(tmp_path):
    pdf = tmp_path / "linked.pdf"
    pdf.write_bytes(b"%PDF fixture")
    attachment = {"key": "ATTACH2", "data": {"itemType": "attachment", "path": str(pdf)}}

    assert resolve_attachment_pdf_path(attachment, tmp_path) == pdf


def test_find_pdf_for_attachment_key_absolute_linked_path(tmp_path):
    linked = tmp_path / "linked.pdf"
    linked.write_bytes(b"%PDF fixture")

    assert find_pdf_for_attachment_key(tmp_path, "LINKED", {"data": {"path": str(linked)}}) == [linked]


def test_missing_storage_folder_returns_none(tmp_path):
    attachment = {"key": "MISSING", "data": {"itemType": "attachment", "path": "storage:paper.pdf"}}

    assert resolve_attachment_pdf_path(attachment, tmp_path) is None


def test_find_pdf_for_attachment_key_no_pdf(tmp_path):
    folder = tmp_path / "storage" / "NOPDF"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("not a pdf", encoding="utf-8")

    assert find_pdf_for_attachment_key(tmp_path, "NOPDF") == []


def test_fallback_single_pdf_inside_storage_folder(tmp_path):
    pdf = tmp_path / "storage" / "ATTACH3" / "only.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF fixture")
    attachment = {"key": "ATTACH3", "data": {"itemType": "attachment", "title": "Only PDF"}}

    assert resolve_attachment_pdf_path(attachment, tmp_path) == pdf


def test_multiple_pdfs_choose_best_title_match(tmp_path):
    storage = tmp_path / "storage" / "ATTACH4"
    storage.mkdir(parents=True)
    first = storage / "supplement.pdf"
    second = storage / "protein-solvent-effects.pdf"
    first.write_bytes(b"%PDF supplement")
    second.write_bytes(b"%PDF paper")
    attachment = {
        "key": "ATTACH4",
        "data": {"itemType": "attachment", "title": "Protein solvent effects"},
    }

    assert resolve_attachment_pdf_path(attachment, tmp_path) == second


def test_doctor_command_output_formatting(monkeypatch, capsys, tmp_path):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.zotero_data_dir = tmp_path

        def test_connection(self):
            return True

        def limited_items(self, *, limit=1):
            return []

        def items(self):
            return []

    monkeypatch.setattr(cli, "ZoteroLocalClient", FakeClient)

    cli.main(["doctor", "--zotero-data-dir", str(tmp_path)])
    output = capsys.readouterr().out

    assert "PASS" in output
    assert "WARN" in output
    assert "FAIL" in output
    assert "Zotero local API data endpoint" in output


def test_doctor_accepts_storage_path(monkeypatch, capsys, tmp_path):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.storage_path = kwargs.get("storage_path")

        def test_connection(self):
            return True

        def items(self):
            return []

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(cli, "ZoteroLocalClient", FakeClient)

    cli.main(["doctor", "--storage-path", str(storage)])
    output = capsys.readouterr().out

    assert "Zotero storage directory" in output
    assert "PASS" in output


def _write_minimal_pdf(path, text="Protein precipitation storage extraction test " * 20):
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_extract_one_storage_key_command_processes_pdf(tmp_path):
    pdf = tmp_path / "storage" / "ATTACHPDF" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    _write_minimal_pdf(pdf)
    output = tmp_path / "out"

    cli.main(
        [
            "extract-one-storage-key",
            "--attachment-key",
            "ATTACHPDF",
            "--zotero-data-dir",
            str(tmp_path),
            "--output",
            str(output),
        ]
    )

    markdown_files = [path for path in output.glob("*.md") if path.name != "failure_report.md"]
    assert markdown_files
    assert "Protein precipitation storage extraction test" in markdown_files[0].read_text(encoding="utf-8")


def test_extract_storage_command_processes_all_pdfs(tmp_path):
    pdf = tmp_path / "storage" / "ATTACHALL" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    _write_minimal_pdf(pdf)
    output = tmp_path / "out-all"

    cli.main(["extract-storage", "--storage-path", str(tmp_path / "storage"), "--output", str(output), "--all-pdfs"])

    markdown_files = [path for path in output.glob("*.md") if path.name != "failure_report.md"]
    assert markdown_files


def test_extract_storage_query_filters_pdfs(tmp_path):
    first = tmp_path / "storage" / "A1" / "protein-precipitation.pdf"
    second = tmp_path / "storage" / "A2" / "unrelated.pdf"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    _write_minimal_pdf(first)
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Chromatography control model " * 20)
    document.save(second)
    document.close()
    output = tmp_path / "out-query"

    cli.main(
        [
            "extract-storage",
            "--storage-path",
            str(tmp_path / "storage"),
            "--output",
            str(output),
            "--query",
            "protein precipitation",
        ]
    )

    markdown_files = [path for path in output.glob("*.md") if path.name != "failure_report.md"]
    assert len(markdown_files) == 1


def test_trace_item_writes_trace_json(monkeypatch, tmp_path):
    pdf = tmp_path / "storage" / "ATTACHTRACE" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    _write_minimal_pdf(pdf)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.storage_path = kwargs["storage_path"]
            self.zotero_data_dir = kwargs.get("zotero_data_dir")

        def item(self, item_key):
            return cli.ZoteroItem(key=item_key, data={"title": "Trace Paper"}, raw={})

        def child_attachments(self, item_key):
            return [{"key": "ATTACHTRACE", "data": {"itemType": "attachment", "title": "Trace PDF"}}]

        def resolve_pdf_paths(self, attachment):
            return find_pdfs_for_attachment_key(self.storage_path, "ATTACHTRACE", attachment)

    monkeypatch.setattr(cli, "ZoteroLocalClient", FakeClient)
    output = tmp_path / "trace-out"

    cli.main(
        [
            "trace-item",
            "--item-key",
            "PARENT1",
            "--storage-path",
            str(tmp_path / "storage"),
            "--output",
            str(output),
        ]
    )

    trace = (output / "zotero_lit_md_trace.json").read_text(encoding="utf-8")
    assert "PARENT1" in trace
    assert "ATTACHTRACE" in trace
    assert "output_markdown_path" in trace


def test_scan_storage_reports_counts(capsys, tmp_path):
    first = tmp_path / "storage" / "A1" / "one.pdf"
    second = tmp_path / "storage" / "A2" / "two.PDF"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"%PDF one")
    second.write_bytes(b"%PDF two")

    cli.main(["scan-storage", "--zotero-data-dir", str(tmp_path)])
    output = capsys.readouterr().out

    assert "total attachment folders" in output
    assert "folders containing PDFs" in output
    assert "PDF files" in output
    assert "2" in output
