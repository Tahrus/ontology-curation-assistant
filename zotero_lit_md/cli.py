from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from zotero_lit_md.local_pdf import (
    ExtractedPdf,
    extract_pdf_text,
    find_pdfs,
    write_extracted_pdf_markdown,
)
from zotero_lit_md.markdown_writer import write_combined_corpus, write_paper_markdown
from zotero_lit_md.pdf_extractor import extract_pdf_to_paper
from zotero_lit_md.schema import PaperMetadata
from zotero_lit_md.zotero_client import (
    ZoteroItem,
    ZoteroLocalClient,
    can_open_pdf,
    find_pdfs_for_attachment_key,
    is_attachment,
    resolve_zotero_data_dir,
)


console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Zotero local PDFs to LLM-ready Markdown.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--collection", help="Zotero collection key or collection name.")
    selector.add_argument("--saved-search", help="Zotero saved search key or saved search name, if exposed by the local API.")
    selector.add_argument("--item-keys", nargs="+", help="Specific Zotero parent item keys.")
    selector.add_argument("--all-with-pdfs", action="store_true", help="Process all Zotero items with PDF attachments.")
    parser.add_argument("--output", required=True, type=Path, help="Directory where Markdown files will be written.")
    parser.add_argument("--json-sidecar", action="store_true", help="Write structured JSON sidecars.")
    parser.add_argument("--combined-corpus", action="store_true", help="Write combined_corpus.md.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Markdown/JSON files.")
    parser.add_argument("--max-papers", type=int, help="Maximum number of parent papers to process.")
    parser.add_argument("--verbose", action="store_true", help="Print per-paper progress details.")
    parser.add_argument("--ocr", action="store_true", help="Optional OCR fallback for scanned PDFs; off by default.")
    parser.add_argument("--base-url", default="http://127.0.0.1:23119/api/", help="Zotero local API base URL.")
    parser.add_argument("--zotero-data-dir", type=Path, help="Zotero data directory, e.g. C:\\Users\\USER\\Zotero.")
    parser.add_argument("--storage-path", type=Path, help="Zotero storage directory, e.g. C:\\Users\\USER\\Zotero\\storage.")
    parser.add_argument("--first-pdf-only", action="store_true", help="Process only the first PDF attachment per item.")
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "doctor":
        doctor(_doctor_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "extract-one":
        extract_one(_extract_one_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "from-folder":
        from_folder(_from_folder_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "scan-storage":
        scan_storage(_scan_storage_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "extract-storage-folder":
        extract_storage_folder(_extract_storage_folder_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "extract-one-storage-key":
        extract_one_storage_key(_extract_one_storage_key_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "extract-zotero":
        extract_zotero(_extract_zotero_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "extract-storage":
        extract_storage(_extract_storage_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "trace-item":
        trace_item(_trace_item_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "pdf-to-md":
        pdf_to_md(_pdf_to_md_parser().parse_args(argv[1:]))
        return
    if argv and argv[0] == "folder-to-md":
        folder_to_md(_folder_to_md_parser().parse_args(argv[1:]))
        return
    args = build_parser().parse_args(argv)
    client = _client_from_args(args)
    try:
        client.test_connection()
    except Exception as exc:
        raise SystemExit(f"Could not connect to Zotero local API at {args.base_url}: {exc}") from exc

    items = _selected_items(client, args)
    if args.max_papers is not None:
        items = items[: args.max_papers]
    output_paths: list[Path] = []
    failed: list[tuple[str, str]] = []
    partial = 0
    successful = 0
    existing_names: set[str] = set()

    for item in items:
        try:
            result = _process_item(client, item, args, existing_names)
            output_paths.extend(result["paths"])
            successful += result["successful"]
            partial += result["partial"]
            failed.extend(result["failed"])
        except Exception as exc:
            failed.append((item.key, str(exc)))
            continue

    if args.combined_corpus and output_paths:
        write_combined_corpus(output_paths, args.output, overwrite=args.overwrite)
    _write_failure_report(args.output, failed)
    _print_summary(len(items), successful, partial, failed, args.output)
    _exit_if_no_markdown(output_paths, failed)


def _doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose Zotero local API and PDF extraction readiness.")
    parser.add_argument("--base-url", default="http://127.0.0.1:23119/api/", help="Zotero local API base URL.")
    parser.add_argument("--zotero-data-dir", type=Path, help="Zotero data directory.")
    parser.add_argument("--storage-path", type=Path, help="Zotero storage directory.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _extract_one_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Debug extraction for one Zotero item key.")
    parser.add_argument("--item-key", required=True, help="Zotero parent item key.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--zotero-data-dir", type=Path, help="Zotero data directory.")
    parser.add_argument("--storage-path", type=Path, help="Zotero storage directory.")
    parser.add_argument("--base-url", default="http://127.0.0.1:23119/api/", help="Zotero local API base URL.")
    parser.add_argument("--json-sidecar", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--first-pdf-only", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    return parser


def _from_folder_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract every PDF in a folder without using Zotero.")
    parser.add_argument("path", type=Path, help="Folder containing PDFs.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--json-sidecar", action="store_true")
    parser.add_argument("--combined-corpus", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    return parser


def _scan_storage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan local Zotero storage for PDFs without using the API.")
    parser.add_argument("--zotero-data-dir", type=Path, help="Zotero data directory.")
    parser.add_argument("--storage-path", type=Path, help="Zotero storage directory.")
    return parser


def _extract_storage_folder_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract every PDF under Zotero storage without using the API.")
    parser.add_argument("--zotero-data-dir", type=Path, help="Zotero data directory.")
    parser.add_argument("--storage-path", type=Path, help="Zotero storage directory.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--json-sidecar", action="store_true")
    parser.add_argument("--combined-corpus", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    return parser


def _extract_one_storage_key_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract PDFs from one Zotero storage attachment folder.")
    parser.add_argument("--attachment-key", required=True, help="Zotero attachment key.")
    parser.add_argument("--zotero-data-dir", type=Path, help="Zotero data directory.")
    parser.add_argument("--storage-path", type=Path, help="Zotero storage directory.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--json-sidecar", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    return parser


def _extract_zotero_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Zotero-selected local storage PDFs to Markdown.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--collection", help="Zotero collection name.")
    selector.add_argument("--collection-key", help="Zotero collection key.")
    selector.add_argument("--item-keys", nargs="+", help="Zotero parent item keys.")
    selector.add_argument("--all-with-pdfs", action="store_true", help="Process all Zotero items with local PDFs.")
    parser.add_argument("--storage-path", required=True, type=Path, help="Zotero storage directory.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--base-url", default="http://127.0.0.1:23119/api/", help="Zotero local API base URL.")
    parser.add_argument("--json-sidecar", action="store_true")
    parser.add_argument("--combined-corpus", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-papers", type=int)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--first-pdf-only", action="store_true")
    return parser


def _extract_storage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract PDFs from a Zotero storage folder without using the API.")
    parser.add_argument("--storage-path", required=True, type=Path, help="Zotero storage directory.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all-pdfs", action="store_true", help="Process every PDF under storage.")
    mode.add_argument("--query", help="Search terms used to rank and filter PDFs.")
    parser.add_argument("--json-sidecar", action="store_true")
    parser.add_argument("--combined-corpus", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    return parser


def _trace_item_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trace one Zotero parent item to child attachment folders and Markdown output.")
    parser.add_argument("--item-key", required=True, help="Zotero parent item key.")
    parser.add_argument("--storage-path", required=True, type=Path, help="Zotero storage directory.")
    parser.add_argument("--output", required=True, type=Path, help="Trace output directory.")
    parser.add_argument("--base-url", default="http://127.0.0.1:23119/api/", help="Zotero local API base URL.")
    parser.add_argument("--json-sidecar", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    return parser


def _pdf_to_md_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert one local PDF file to LLM-ready Markdown.")
    parser.add_argument("--pdf", required=True, type=Path, help="Local PDF file.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _folder_to_md_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert local PDFs in a folder to LLM-ready Markdown.")
    parser.add_argument("--folder", required=True, type=Path, help="Folder containing PDFs.")
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--recursive", action="store_true", help="Scan recursively for PDFs.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def doctor(args: argparse.Namespace) -> None:
    storage_dir = _storage_dir_from_args(args)
    zotero_data_dir = _zotero_data_dir_from_args(args)
    rows: list[tuple[str, str, str]] = []

    if zotero_data_dir and zotero_data_dir.exists():
        rows.append(("PASS", "Zotero data directory", str(zotero_data_dir)))
    elif zotero_data_dir:
        rows.append(("WARN", "Zotero data directory", f"Configured path does not exist: {zotero_data_dir}"))
    else:
        rows.append(("WARN", "Zotero data directory", "Not supplied; using storage path directly"))

    if storage_dir and storage_dir.exists():
        rows.append(("PASS", "Zotero storage directory", str(storage_dir)))
    else:
        rows.append(("FAIL", "Zotero storage directory", f"Missing: {storage_dir}" if storage_dir else "No data dir"))

    storage_pdfs = _storage_pdfs(storage_dir) if storage_dir and storage_dir.exists() else []
    rows.append(("PASS" if storage_pdfs else "WARN", "Local storage PDF scan", f"{len(storage_pdfs)} PDFs found"))

    extracted_chars = 0
    if storage_pdfs:
        try:
            import fitz

            with fitz.open(storage_pdfs[0]) as document:
                extracted_chars = len(document[0].get_text()) if document.page_count else 0
            rows.append(("PASS", "PyMuPDF opens local PDF", str(storage_pdfs[0])))
        except Exception as exc:
            rows.append(("FAIL", "PyMuPDF opens local PDF", str(exc)))
    else:
        rows.append(("FAIL", "PyMuPDF opens local PDF", "No local storage PDF found"))

    rows.append(("PASS" if extracted_chars >= 500 else "WARN", "Extract at least 500 chars", f"{extracted_chars} characters from first local PDF"))

    client = ZoteroLocalClient(args.base_url, timeout=8, zotero_data_dir=zotero_data_dir, storage_path=storage_dir)
    first_attachment: dict[str, Any] | None = None
    try:
        client.test_connection()
        rows.append(("PASS", "Zotero local API data endpoint", "users/0/items?limit=1 works"))
        for item in client.items():
            attachments = [attachment for attachment in client.child_attachments(item.key) if is_attachment(attachment)]
            first_attachment = next((attachment for attachment in attachments if client.resolve_pdf_paths(attachment)), None)
            if first_attachment:
                break
        rows.append(("PASS" if first_attachment else "WARN", "API attachment key maps to storage folder", _attachment_summary(first_attachment) if first_attachment else "No API child mapped to a local PDF"))
    except Exception as exc:
        rows.append(("FAIL", "Zotero local API data endpoint", str(exc)))
    _print_doctor(rows)


def extract_one(args: argparse.Namespace) -> None:
    client = _client_from_args(args)
    item = client.item(args.item_key)
    result = _process_item(client, item, args, set())
    _write_failure_report(args.output, result["failed"])
    _print_summary(1, result["successful"], result["partial"], result["failed"], args.output)


def from_folder(args: argparse.Namespace) -> None:
    if not args.path.exists() or not args.path.is_dir():
        raise SystemExit(f"PDF folder does not exist: {args.path}")
    output_paths: list[Path] = []
    failed: list[tuple[str, str]] = []
    successful = 0
    partial = 0
    existing_names: set[str] = set()
    for pdf_path in sorted(args.path.rglob("*.pdf")):
        metadata = PaperMetadata(
            title=pdf_path.stem,
            pdf_filename=pdf_path.name,
            pdf_path=str(pdf_path),
            zotero_item_key=pdf_path.stem,
            lead_author="folder",
        )
        try:
            paper = extract_pdf_to_paper(pdf_path, metadata, ocr=args.ocr)
            path = write_paper_markdown(
                paper,
                args.output,
                json_sidecar=args.json_sidecar,
                overwrite=args.overwrite,
                existing_names=existing_names,
            )
            existing_names.add(path.name)
            output_paths.append(path)
            if args.verbose:
                console.print(f"[green]wrote[/green] {path} ({sum(len(page.text) for page in paper.pages)} chars)")
            if paper.diagnostics.extraction_status == "complete":
                successful += 1
            elif paper.diagnostics.extraction_status in {"partial", "warning"}:
                partial += 1
            else:
                failed.append((str(pdf_path), "; ".join(paper.diagnostics.warnings) or "Extraction failed."))
        except Exception as exc:
            failed.append((str(pdf_path), str(exc)))
    if args.combined_corpus and output_paths:
        write_combined_corpus(output_paths, args.output, overwrite=args.overwrite)
    _write_failure_report(args.output, failed)
    _print_summary(len(output_paths) + len(failed), successful, partial, failed, args.output)


def scan_storage(args: argparse.Namespace) -> None:
    storage_dir = _storage_dir_from_args(args)
    if not storage_dir.exists():
        console.print(f"[yellow]warning[/yellow] storage directory does not exist: {storage_dir}")
        return
    attachment_folders = sorted(path for path in storage_dir.iterdir() if path.is_dir())
    pdfs = _storage_pdfs(storage_dir)
    folders_with_pdfs = {pdf.parent for pdf in pdfs}
    table = Table(title="Zotero Storage Scan")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("storage directory", str(storage_dir))
    table.add_row("total attachment folders", str(len(attachment_folders)))
    table.add_row("folders containing PDFs", str(len(folders_with_pdfs)))
    table.add_row("PDF files", str(len(pdfs)))
    console.print(table)
    console.print("[bold]First 20 detected PDFs[/bold]")
    for pdf in pdfs[:20]:
        console.print(_console_text(pdf))


def extract_storage_folder(args: argparse.Namespace) -> None:
    storage_dir = _storage_dir_from_args(args)
    if not storage_dir.exists():
        raise SystemExit(f"Zotero storage directory does not exist: {storage_dir}")
    _extract_pdf_paths(
        _storage_pdfs(storage_dir),
        args.output,
        json_sidecar=args.json_sidecar,
        combined_corpus=args.combined_corpus,
        overwrite=args.overwrite,
        verbose=args.verbose,
        ocr=args.ocr,
    )


def extract_one_storage_key(args: argparse.Namespace) -> None:
    storage_dir = _storage_dir_from_args(args)
    attachment_dir = storage_dir / args.attachment_key
    pdfs = find_pdfs_for_attachment_key(storage_dir, args.attachment_key)
    if args.verbose:
        console.print("[bold]Child attachment[/bold]")
        console.print(f"  key: {args.attachment_key}")
        console.print(f"  storage folder: {attachment_dir}")
        console.print(f"  storage folder exists: {attachment_dir.exists()}")
        console.print("  PDFs found in folder:")
        for pdf in pdfs:
            console.print(f"    - {_console_text(pdf)}")
    _extract_pdf_paths(
        pdfs,
        args.output,
        json_sidecar=args.json_sidecar,
        combined_corpus=False,
        overwrite=args.overwrite,
        verbose=args.verbose,
        ocr=args.ocr,
        zotero_item_key=args.attachment_key,
    )


def extract_zotero(args: argparse.Namespace) -> None:
    client = _client_from_args(args)
    try:
        client.test_connection()
    except Exception as exc:
        raise SystemExit(f"Could not connect to Zotero local API at {args.base_url}: {exc}") from exc
    items = _selected_items(client, args)
    if args.max_papers is not None:
        items = items[: args.max_papers]
    output_paths: list[Path] = []
    failed: list[tuple[str, str]] = []
    successful = 0
    partial = 0
    existing_names: set[str] = set()
    child_count = 0
    folders_found = 0
    pdf_count = 0
    for item in items:
        result = _process_item(client, item, args, existing_names)
        output_paths.extend(result["paths"])
        failed.extend(result["failed"])
        successful += result["successful"]
        partial += result["partial"]
        child_count += result.get("child_attachments", 0)
        folders_found += result.get("storage_folders_found", 0)
        pdf_count += result.get("pdfs_found", 0)
    if args.combined_corpus and output_paths:
        write_combined_corpus(output_paths, args.output, overwrite=args.overwrite)
    _write_failure_report(args.output, failed)
    _print_extraction_counts(
        selected_items=len(items),
        child_attachments=child_count,
        folders_found=folders_found,
        pdfs_found=pdf_count,
        pdfs_opened=successful + partial,
        markdown_written=len(output_paths),
        failed=failed,
    )
    _print_summary(len(items), successful, partial, failed, args.output)
    _exit_if_no_markdown(output_paths, failed)


def extract_storage(args: argparse.Namespace) -> None:
    storage_dir = _storage_dir_from_args(args)
    if not storage_dir.exists():
        raise SystemExit(f"Zotero storage directory does not exist: {storage_dir}")
    pdfs = _storage_pdfs(storage_dir)
    if args.query:
        pdfs = _rank_storage_pdfs(pdfs, args.query)
    _extract_pdf_paths(
        pdfs,
        args.output,
        json_sidecar=args.json_sidecar,
        combined_corpus=args.combined_corpus,
        overwrite=args.overwrite,
        verbose=args.verbose,
        ocr=args.ocr,
        exit_on_zero=True,
    )


def trace_item(args: argparse.Namespace) -> None:
    client = _client_from_args(args)
    item = client.item(args.item_key)
    args.output.mkdir(parents=True, exist_ok=True)
    existing_names: set[str] = set()
    trace: dict[str, Any] = {
        "parent_item_key": item.key,
        "parent_metadata": item.data,
        "child_attachments": [],
        "final_status": "failed",
    }
    written: list[Path] = []
    failed: list[tuple[str, str]] = []
    attachments = [attachment for attachment in client.child_attachments(item.key) if is_attachment(attachment)]
    for attachment in attachments:
        attachment_key = _attachment_key(attachment)
        storage_folder = client.storage_path / attachment_key if client.storage_path else None
        pdfs = client.resolve_pdf_paths(attachment)
        entry: dict[str, Any] = {
            "attachment_key": attachment_key,
            "attachment_metadata": attachment.get("data") or {},
            "expected_storage_folder": str(storage_folder or ""),
            "storage_folder_exists": bool(storage_folder and storage_folder.exists()),
            "pdf_files_found": [str(pdf) for pdf in pdfs],
            "selected_pdf_path": str(pdfs[0]) if pdfs else "",
            "pymupdf_open_status": "not_attempted",
            "page_count": 0,
            "extracted_character_count": 0,
            "output_markdown_path": "",
            "final_status": "failed",
        }
        if pdfs:
            pdf_path = pdfs[0]
            entry["pymupdf_open_status"] = "OK" if can_open_pdf(pdf_path) else "FAIL"
            metadata = _metadata_from_item(item, attachment, pdf_path, collection=getattr(args, "collection", None))
            try:
                paper = extract_pdf_to_paper(pdf_path, metadata, ocr=args.ocr)
                path = write_paper_markdown(
                    paper,
                    args.output,
                    json_sidecar=args.json_sidecar,
                    overwrite=args.overwrite,
                    existing_names=existing_names,
                )
                existing_names.add(path.name)
                written.append(path)
                entry["page_count"] = paper.diagnostics.pdf_pages
                entry["extracted_character_count"] = paper.diagnostics.extracted_characters
                entry["output_markdown_path"] = str(path)
                entry["final_status"] = paper.diagnostics.extraction_status
            except Exception as exc:
                failed.append((attachment_key, str(exc)))
                entry["failure_reason"] = str(exc)
        trace["child_attachments"].append(entry)
    trace["final_status"] = "complete" if written else "failed"
    trace_path = args.output / "zotero_lit_md_trace.json"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.verbose:
        console.print(f"[bold]trace JSON[/bold] {_console_text(trace_path)}")
    _print_extraction_counts(
        selected_items=1,
        child_attachments=len(attachments),
        folders_found=sum(1 for entry in trace["child_attachments"] if entry["storage_folder_exists"]),
        pdfs_found=sum(len(entry["pdf_files_found"]) for entry in trace["child_attachments"]),
        pdfs_opened=len(written),
        markdown_written=len(written),
        failed=failed,
    )
    _exit_if_no_markdown(written, failed)


def pdf_to_md(args: argparse.Namespace) -> None:
    if not args.pdf.exists() or not args.pdf.is_file():
        raise SystemExit(f"PDF does not exist: {args.pdf}")
    results = [_write_local_pdf(args.pdf, args.output, overwrite=args.overwrite, verbose=args.verbose)]
    _print_local_summary(results, args.output)
    _exit_if_no_local_markdown(results)


def folder_to_md(args: argparse.Namespace) -> None:
    if not args.folder.exists() or not args.folder.is_dir():
        raise SystemExit(f"PDF folder does not exist: {args.folder}")
    pdfs = find_pdfs(args.folder, recursive=args.recursive)
    if not pdfs:
        raise SystemExit(f"No PDFs found in: {args.folder}")
    results = [
        _write_local_pdf(pdf_path, args.output, overwrite=args.overwrite, verbose=args.verbose)
        for pdf_path in pdfs
    ]
    _print_local_summary(results, args.output)
    _exit_if_no_local_markdown(results)


def _write_local_pdf(pdf_path: Path, output_dir: Path, *, overwrite: bool, verbose: bool) -> dict[str, Any]:
    extracted = extract_pdf_text(pdf_path)
    markdown_path = write_extracted_pdf_markdown(extracted, output_dir, overwrite=overwrite)
    if verbose:
        _print_local_pdf_verbose(extracted, markdown_path)
    return {"pdf": extracted, "markdown_path": markdown_path}


def _print_local_pdf_verbose(extracted: ExtractedPdf, markdown_path: Path | None) -> None:
    console.print(f"PDF: {_console_text(extracted.pdf_path)}")
    console.print(f"  exists: {extracted.pdf_path.exists()}")
    console.print(f"  size: {extracted.pdf_path.stat().st_size if extracted.pdf_path.exists() else 0} bytes")
    console.print(f"  opened: {extracted.extraction_status != 'failed'}")
    console.print(f"  pages: {extracted.page_count}")
    console.print(f"  extracted characters: {extracted.total_char_count}")
    console.print(f"  extraction status: {extracted.extraction_status}")
    console.print(f"  markdown written: {_console_text(markdown_path or '')}")


def _print_local_summary(results: list[dict[str, Any]], output_dir: Path) -> None:
    pdfs = [result["pdf"] for result in results]
    opened = sum(1 for pdf in pdfs if pdf.extraction_status != "failed")
    written = sum(1 for result in results if result["markdown_path"])
    partial = sum(1 for pdf in pdfs if pdf.extraction_status == "partial_or_empty")
    failed = sum(1 for pdf in pdfs if pdf.extraction_status == "failed")
    console.print("Summary")
    console.print(f"PDFs found: {len(pdfs)}")
    console.print(f"PDFs opened: {opened}")
    console.print(f"Markdown files written: {written}")
    console.print(f"Partial or empty PDFs: {partial}")
    console.print(f"Failed PDFs: {failed}")
    console.print(f"Output directory: {_console_text(output_dir)}")


def _exit_if_no_local_markdown(results: list[dict[str, Any]]) -> None:
    if any(result["markdown_path"] for result in results):
        return
    raise SystemExit("Markdown files written: 0")


def _extract_pdf_paths(
    pdf_paths: list[Path],
    output_dir: Path,
    *,
    json_sidecar: bool,
    combined_corpus: bool,
    overwrite: bool,
    verbose: bool,
    ocr: bool,
    zotero_item_key: str | None = None,
    exit_on_zero: bool = False,
) -> None:
    output_paths: list[Path] = []
    failed: list[tuple[str, str]] = []
    successful = 0
    partial = 0
    existing_names: set[str] = set()
    for pdf_path in pdf_paths:
        metadata = PaperMetadata(
            title=pdf_path.stem,
            pdf_filename=pdf_path.name,
            pdf_path=str(pdf_path),
            zotero_item_key=zotero_item_key or pdf_path.parent.name,
            lead_author="storage",
        )
        try:
            paper = extract_pdf_to_paper(pdf_path, metadata, ocr=ocr)
            path = write_paper_markdown(
                paper,
                output_dir,
                json_sidecar=json_sidecar,
                overwrite=overwrite,
                existing_names=existing_names,
            )
            existing_names.add(path.name)
            output_paths.append(path)
            extracted_chars = sum(len(page.text) for page in paper.pages)
            if verbose:
                console.print(f"[bold]selected PDF[/bold] {_console_text(pdf_path)}")
                console.print(f"[bold]file size[/bold] {pdf_path.stat().st_size}")
                console.print(f"[bold]PyMuPDF open[/bold] {'OK' if can_open_pdf(pdf_path) else 'FAIL'}")
                console.print(f"[bold]extracted characters[/bold] {extracted_chars}")
                console.print(f"[bold]output Markdown[/bold] {_console_text(path)}")
            if paper.diagnostics.extraction_status == "complete":
                successful += 1
            elif paper.diagnostics.extraction_status in {"partial", "warning"}:
                partial += 1
            else:
                failed.append((str(pdf_path), "; ".join(paper.diagnostics.warnings) or "Extraction failed."))
        except Exception as exc:
            failed.append((str(pdf_path), str(exc)))
    if combined_corpus and output_paths:
        write_combined_corpus(output_paths, output_dir, overwrite=overwrite)
    _write_failure_report(output_dir, failed)
    _print_summary(len(pdf_paths), successful, partial, failed, output_dir)
    if exit_on_zero:
        _exit_if_no_markdown(output_paths, failed)


def _selected_items(client: ZoteroLocalClient, args: argparse.Namespace) -> list[ZoteroItem]:
    if getattr(args, "collection", None):
        return client.collection_items(args.collection)
    if getattr(args, "collection_key", None):
        return client.collection_items(args.collection_key)
    if getattr(args, "saved_search", None):
        return client.saved_search_items(args.saved_search)
    if getattr(args, "item_keys", None):
        return client.items_by_keys(args.item_keys)
    return list(client.all_items_with_pdfs(max_papers=getattr(args, "max_papers", None)))


def _process_item(
    client: ZoteroLocalClient,
    item: ZoteroItem,
    args: argparse.Namespace,
    existing_names: set[str],
) -> dict[str, Any]:
    if args.verbose:
        console.print(f"[bold]Parent item[/bold] {_console_text(item.key)}")
        console.print(f"[bold]Parent title[/bold] {_console_text(item.data.get('title', ''))}")
    attachments = [attachment for attachment in client.child_attachments(item.key) if is_attachment(attachment)]
    if getattr(args, "first_pdf_only", False):
        attachments = attachments[:1]
    if args.verbose:
        console.print(f"[bold]Child attachment keys[/bold] {', '.join(_attachment_key(a) for a in attachments) or 'none'}")
    if not attachments:
        return {
            "paths": [],
            "successful": 0,
            "partial": 0,
            "failed": [(item.key, "No child attachments found.")],
            "child_attachments": 0,
            "storage_folders_found": 0,
            "pdfs_found": 0,
        }

    output_paths: list[Path] = []
    failed: list[tuple[str, str]] = []
    successful = 0
    partial = 0
    folders_found = 0
    pdfs_found = 0
    for attachment in attachments:
        pdf_paths = client.resolve_pdf_paths(attachment)
        storage_folder = _attachment_storage_folder(client, attachment)
        if storage_folder and storage_folder.exists():
            folders_found += 1
        pdfs_found += len(pdf_paths)
        _verbose_attachment(client, item, attachment, pdf_paths, args.verbose)
        if not pdf_paths:
            failed.append((item.key, "No PDF files were found in the attachment storage folder or linked path."))
            continue
        for pdf_path in pdf_paths:
            metadata = _metadata_from_item(item, attachment, pdf_path, collection=getattr(args, "collection", None))
            paper = extract_pdf_to_paper(pdf_path, metadata, ocr=args.ocr)
            path = write_paper_markdown(
                paper,
                args.output,
                json_sidecar=getattr(args, "json_sidecar", False),
                overwrite=getattr(args, "overwrite", False),
                existing_names=existing_names,
            )
            existing_names.add(path.name)
            output_paths.append(path)
            extracted_chars = sum(len(page.text) for page in paper.pages)
            if args.verbose:
                console.print(f"[bold]selected PDF[/bold] {_console_text(pdf_path)}")
                console.print(f"[bold]file size[/bold] {pdf_path.stat().st_size if pdf_path.exists() else 0}")
                console.print(f"[bold]PyMuPDF open[/bold] {'OK' if can_open_pdf(pdf_path) else 'FAIL'}")
                console.print(f"[bold]pages[/bold] {len(paper.pages)}")
                console.print(f"[bold]extracted characters[/bold] {extracted_chars}")
                console.print(f"[bold]output Markdown[/bold] {_console_text(path)}")
            if paper.diagnostics.extraction_status == "complete":
                successful += 1
            elif paper.diagnostics.extraction_status in {"partial", "warning"}:
                partial += 1
            else:
                failed.append((item.key, "; ".join(paper.diagnostics.warnings) or "Extraction failed."))
    return {
        "paths": output_paths,
        "successful": successful,
        "partial": partial,
        "failed": failed,
        "child_attachments": len(attachments),
        "storage_folders_found": folders_found,
        "pdfs_found": pdfs_found,
    }


def _verbose_attachment(
    client: ZoteroLocalClient,
    item: ZoteroItem,
    attachment: dict[str, Any],
    pdf_paths: list[Path],
    verbose: bool,
) -> None:
    if not verbose:
        return
    data = attachment.get("data") or {}
    attachment_key = _attachment_key(attachment)
    storage_folder = _attachment_storage_folder(client, attachment)
    console.print("[bold]Child attachment[/bold]")
    console.print(f"  key: {_console_text(attachment_key)}")
    console.print(f"  title: {_console_text(data.get('title', ''))}")
    console.print(f"  API path hint: {_console_text(data.get('path') or data.get('localPath') or '')}")
    console.print(f"  storage folder: {_console_text(storage_folder or '')}")
    console.print(f"  storage folder exists: {bool(storage_folder and storage_folder.exists())}")
    console.print("  PDFs found in folder:")
    for pdf_path in pdf_paths:
        console.print(f"    - {_console_text(pdf_path)}")


def _attachment_key(attachment: dict[str, Any]) -> str:
    data = attachment.get("data") or {}
    return str(attachment.get("key") or data.get("key") or "")


def _attachment_summary(attachment: dict[str, Any] | None) -> str:
    if not attachment:
        return ""
    data = attachment.get("data") or {}
    return f"{_attachment_key(attachment)} {data.get('title') or data.get('filename') or ''}".strip()


def _print_doctor(rows: list[tuple[str, str, str]]) -> None:
    table = Table(title="Zotero Markdown Export Doctor")
    table.add_column("Status")
    table.add_column("Check")
    table.add_column("Detail")
    for status, check, detail in rows:
        style = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}.get(status, "")
        table.add_row(f"[{style}]{status}[/{style}]" if style else status, check, detail)
    console.print(table)


def _client_from_args(args: argparse.Namespace) -> ZoteroLocalClient:
    storage_path = _storage_dir_from_args(args)
    return ZoteroLocalClient(
        getattr(args, "base_url", "http://127.0.0.1:23119/api/"),
        zotero_data_dir=_zotero_data_dir_from_args(args),
        storage_path=storage_path,
    )


def _zotero_data_dir_from_args(args: argparse.Namespace) -> Path | None:
    if getattr(args, "zotero_data_dir", None):
        return args.zotero_data_dir.expanduser()
    if getattr(args, "storage_path", None):
        storage_path = args.storage_path.expanduser()
        if storage_path.name.casefold() == "storage":
            return storage_path.parent
    return resolve_zotero_data_dir(None)


def _storage_dir_from_args(args: argparse.Namespace) -> Path:
    if getattr(args, "storage_path", None):
        return args.storage_path.expanduser()
    return _storage_dir_from_data_dir(resolve_zotero_data_dir(getattr(args, "zotero_data_dir", None)))


def _storage_dir_from_data_dir(zotero_data_dir: Path | None) -> Path:
    if zotero_data_dir is None:
        raise SystemExit("Zotero data directory was not supplied and could not be autodetected.")
    return zotero_data_dir.expanduser() / "storage"


def _storage_pdfs(storage_dir: Path | None) -> list[Path]:
    if storage_dir is None or not storage_dir.exists():
        return []
    return sorted(
        {
            path.resolve()
            for pattern in ("*.pdf", "*.PDF")
            for path in storage_dir.rglob(pattern)
            if path.is_file()
        }
    )


def _console_text(value: Any) -> str:
    text = str(value)
    encoding = getattr(console.file, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _attachment_storage_folder(client: ZoteroLocalClient, attachment: dict[str, Any]) -> Path | None:
    if client.storage_path is None:
        return None
    return client.storage_path / _attachment_key(attachment)


def _rank_storage_pdfs(pdf_paths: list[Path], query: str) -> list[Path]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    ranked: list[tuple[int, str, Path]] = []
    for pdf_path in pdf_paths:
        score = 0
        haystacks = [pdf_path.name.casefold(), pdf_path.parent.name.casefold()]
        for term in terms:
            score += sum(3 for haystack in haystacks if term in haystack)
        first_page = _first_page_text(pdf_path).casefold()
        for term in terms:
            if term in first_page:
                score += 1
        if score > 0:
            ranked.append((-score, str(pdf_path), pdf_path))
    return [path for _, _, path in sorted(ranked)]


def _first_page_text(pdf_path: Path) -> str:
    try:
        import fitz

        with fitz.open(pdf_path) as document:
            return document[0].get_text() if document.page_count else ""
    except Exception:
        return ""


def _print_extraction_counts(
    *,
    selected_items: int,
    child_attachments: int,
    folders_found: int,
    pdfs_found: int,
    pdfs_opened: int,
    markdown_written: int,
    failed: list[tuple[str, str]],
) -> None:
    console.print(f"Selected Zotero parent items: {selected_items}")
    console.print(f"Child attachments found: {child_attachments}")
    console.print(f"Attachment storage folders found: {folders_found}")
    console.print(f"PDFs found: {pdfs_found}")
    console.print(f"PDFs opened: {pdfs_opened}")
    console.print(f"Markdown files written: {markdown_written}")
    if failed:
        console.print(f"Failure reason: {_console_text(failed[0][1])}")


def _exit_if_no_markdown(output_paths: list[Path], failed: list[tuple[str, str]]) -> None:
    if output_paths:
        return
    reason = failed[0][1] if failed else "No PDFs matched the requested selection."
    raise SystemExit(f"Markdown files written: 0\nFailure reason: {reason}")


def _metadata_from_item(
    item: ZoteroItem,
    attachment: dict[str, Any],
    pdf_path: Path | None,
    *,
    collection: str | None,
) -> PaperMetadata:
    data = item.data
    attachment_data = attachment.get("data") or {}
    authors = _authors(data.get("creators") or [])
    lead_author = _lead_author(authors)
    year = _year(data.get("date") or data.get("year"))
    title = str(data.get("title") or "Untitled paper")
    return PaperMetadata(
        title=title,
        doi=str(data.get("DOI") or data.get("doi") or ""),
        citation=" ".join(part for part in [f"{lead_author} et al." if lead_author else "", year] if part),
        authors=authors,
        year=year,
        journal=str(data.get("publicationTitle") or data.get("journalAbbreviation") or ""),
        volume=str(data.get("volume") or ""),
        issue=str(data.get("issue") or ""),
        pages_or_article_number=str(data.get("pages") or data.get("number") or ""),
        zotero_item_key=item.key,
        zotero_attachment_key=_attachment_key(attachment),
        zotero_collection=collection or "",
        pdf_filename=str(attachment_data.get("filename") or attachment_data.get("title") or ""),
        pdf_path=str(pdf_path or ""),
        abstract=str(data.get("abstractNote") or ""),
        keywords=[str(tag.get("tag")) for tag in data.get("tags") or [] if isinstance(tag, dict) and tag.get("tag")],
        lead_author=lead_author,
    )


def _authors(creators: list[dict[str, Any]]) -> list[str]:
    authors = []
    for creator in creators:
        if creator.get("creatorType") not in {None, "author"}:
            continue
        name = " ".join(part for part in [creator.get("firstName"), creator.get("lastName")] if part)
        if not name and creator.get("name"):
            name = str(creator["name"])
        if name:
            authors.append(name)
    return authors


def _lead_author(authors: list[str]) -> str:
    if not authors:
        return ""
    return authors[0].split(",")[0].split()[-1]


def _year(value: Any) -> str:
    import re

    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return match.group(0) if match else ""


def _write_failure_report(output_dir: Path, failed: list[tuple[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Zotero Literature Markdown Failure Report", ""]
    if not failed:
        lines.append("No failures.")
    for key, message in failed:
        lines.append(f"* **{key}:** {message}")
    (output_dir / "failure_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_summary(
    processed: int,
    successful: int,
    partial: int,
    failed: list[tuple[str, str]],
    output_dir: Path,
) -> None:
    table = Table(title="Zotero Markdown Export Summary")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("processed papers", str(processed))
    table.add_row("successful extractions", str(successful))
    table.add_row("partial extractions", str(partial))
    table.add_row("failed papers", str(len(failed)))
    table.add_row("output directory", str(output_dir))
    console.print(table)
