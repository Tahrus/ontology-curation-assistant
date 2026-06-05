"""
Combined bibliography/literature processing pipeline.

This single script merges the functionality of:
- BibImport.py: copy PDFs from Zotero storage into the project PDF folder
- BibConversion.py: convert PDFs into LLM-ready Markdown
- BibStructuring.py: inject generated Markdown into existing paper Markdown files
- BibCombine(1).py: combine all paper Markdown files into one file

Default paths are kept from the original scripts. Override them with CLI flags
when running on another machine or project checkout.

Required for PDF conversion:
    pip install pymupdf

Example full pipeline:
    python BibPipelineCombined.py

Example with custom base directory:
    python BibPipelineCombined.py --base-dir "C:\\Users\\me\\project\\literature"

Example run only selected stages:
    python BibPipelineCombined.py --skip-import --skip-convert
"""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


# ---------------------------------------------------------------------------
# Default paths from the original scripts
# ---------------------------------------------------------------------------

DEFAULT_ZOTERO_STORAGE_DIR = Path(r"C:\Users\ge47vob\Zotero\storage")
DEFAULT_BASE_DIR = Path(
    r"C:\Users\ge47vob\.antigravity\ontology-curation-assistant\literature"
)


@dataclass(frozen=True)
class PipelinePaths:
    zotero_storage_dir: Path
    pdf_dir: Path
    generated_md_dir: Path
    papers_dir: Path
    combined_output_file: Path


# ---------------------------------------------------------------------------
# Stage 1: Import PDFs from Zotero storage
# ---------------------------------------------------------------------------


def unique_destination_path(destination: Path) -> Path:
    """Return a non-existing path by appending _1, _2, ... if needed."""
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    counter = 1

    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def import_pdfs_from_zotero(source_dir: Path, target_dir: Path) -> int:
    """Copy all PDFs from Zotero storage into the project PDF directory."""
    if not source_dir.exists():
        raise FileNotFoundError(f"Zotero storage directory not found: {source_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    copied = 0

    for file_path in sorted(source_dir.rglob("*.pdf")):
        if not file_path.is_file():
            continue

        destination = unique_destination_path(target_dir / file_path.name)
        shutil.copy2(file_path, destination)
        copied += 1
        print(f"Copied: {file_path} -> {destination}")

    print(f"\nPDF import done. Copied {copied} PDF files.")
    return copied


# ---------------------------------------------------------------------------
# Stage 2: Convert PDFs to section-structured Markdown
# ---------------------------------------------------------------------------


SECTION_RE = re.compile(
    r"""
    ^
    (?:
        \d+\.\s+[A-Z][A-Za-z0-9,\-:;()/ ]{3,}              # 1. Introduction
        |
        \d+\.\d+\.\s+[A-Z][A-Za-z0-9,\-:;()/ ]{3,}          # 1.1. Subsection
        |
        \d+\.\d+\.\d+\.\s+[A-Z][A-Za-z0-9,\-:;()/ ]{3,}     # 1.1.1. Subsubsection
        |
        A\s*B\s*S\s*T\s*R\s*A\s*C\s*T                      # ABSTRACT with spacing
        |
        Abstract
        |
        Keywords
        |
        References
        |
        Acknowledg(?:e)?ments
        |
        Supplementary material
        |
        Fig\.\s*\d+\.?.*                                   # Fig. 1. Caption
        |
        Figure\s*\d+\.?.*
        |
        Table\s*\d+\.?.*
    )
    $
    """,
    re.VERBOSE | re.IGNORECASE,
)


def clean_text(text: str) -> str:
    """Clean extracted PDF text while preserving paragraph boundaries."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_heading(text: str) -> str:
    """Normalize common PDF heading artifacts."""
    text = clean_text(text)
    text = re.sub(r"\s+", " ", text)

    if re.fullmatch(r"A\s*B\s*S\s*T\s*R\s*A\s*C\s*T", text, flags=re.IGNORECASE):
        return "ABSTRACT"

    return text.strip()


def heading_level(heading: str) -> int:
    """Assign Markdown heading levels based on section numbering."""
    heading = heading.strip()

    if re.match(r"^\d+\.\d+\.\d+\.", heading):
        return 4
    if re.match(r"^\d+\.\d+\.", heading):
        return 3
    if re.match(r"^\d+\.", heading):
        return 2
    if re.match(r"^(Fig\.|Figure|Table)\s*\d+", heading, flags=re.IGNORECASE):
        return 3

    return 2


def is_likely_heading(line: str) -> bool:
    """Detect article-style headings from extracted text."""
    line = normalize_heading(line)
    return bool(line and len(line) <= 180 and SECTION_RE.match(line))


def extract_pdf_metadata(doc, pdf_path: Path) -> dict[str, str]:
    """Extract available PDF metadata from a PyMuPDF document."""
    metadata = doc.metadata or {}

    return {
        "title": metadata.get("title") or pdf_path.stem,
        "author": metadata.get("author") or "",
        "subject": metadata.get("subject") or "",
        "keywords": metadata.get("keywords") or "",
        "pages": str(doc.page_count),
        "source_file": pdf_path.name,
    }


def extract_structured_lines(pdf_path: Path) -> list[str]:
    """Extract text line-by-line from a PDF using PyMuPDF."""
    try:
        import fitz  # type: ignore
    except ImportError as error:
        raise ImportError(
            "PyMuPDF is required for PDF conversion. Install it with: pip install pymupdf"
        ) from error

    doc = fitz.open(pdf_path)
    lines: list[str] = []

    try:
        for page in doc:
            text = clean_text(page.get_text("text"))
            if not text:
                continue
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    finally:
        doc.close()

    return lines


def lines_to_markdown(lines: list[str]) -> list[str]:
    """Convert extracted PDF lines into section-structured Markdown."""
    markdown: list[str] = []
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer
        if paragraph_buffer:
            paragraph = clean_text(" ".join(paragraph_buffer))
            if paragraph:
                markdown.append(paragraph)
                markdown.append("")
            paragraph_buffer = []

    for raw_line in lines:
        line = normalize_heading(raw_line)

        if not line:
            flush_paragraph()
            continue

        if is_likely_heading(line):
            flush_paragraph()
            level = heading_level(line)
            markdown.append(f"{'#' * level} {line}")
            markdown.append("")
        else:
            paragraph_buffer.append(line)

    flush_paragraph()
    return markdown


def pdf_to_section_markdown(pdf_path: Path, output_path: Path) -> None:
    """Convert one PDF into a section-structured Markdown file."""
    try:
        import fitz  # type: ignore
    except ImportError as error:
        raise ImportError(
            "PyMuPDF is required for PDF conversion. Install it with: pip install pymupdf"
        ) from error

    doc = fitz.open(pdf_path)
    try:
        metadata = extract_pdf_metadata(doc, pdf_path)
    finally:
        doc.close()

    lines = extract_structured_lines(pdf_path)
    body_markdown = lines_to_markdown(lines)

    md: list[str] = [
        f"# {metadata['title']}",
        "",
        "## LLM-ready full-text Markdown",
        "",
        (
            "This Markdown file was generated from a PDF. Images were omitted. "
            "Extracted figure captions, table text, equations, references, and article body text "
            "are retained where the PDF text layer exposed them. The layout was converted into "
            "a single reading order for LLM/RAG ingestion."
        ),
        "",
        "## Minimal metadata",
        "",
        f"- **Title:** {metadata['title']}",
        f"- **Source:** {metadata['source_file']}",
        f"- **Pages:** {metadata['pages']}",
    ]

    if metadata["author"]:
        md.append(f"- **Author:** {metadata['author']}")
    if metadata["subject"]:
        md.append(f"- **Subject:** {metadata['subject']}")
    if metadata["keywords"]:
        md.append(f"- **Keywords:** {metadata['keywords']}")

    md.append("- **Images:** omitted")
    md.append("")
    md.extend(body_markdown)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(md), encoding="utf-8")


def convert_pdfs_to_markdown(source_dir: Path, target_dir: Path) -> tuple[int, int]:
    """Convert all PDFs in source_dir to Markdown files in target_dir."""
    if not source_dir.exists():
        raise FileNotFoundError(f"PDF source directory not found: {source_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = sorted(source_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in: {source_dir}")
        return 0, 0

    converted = 0
    failed = 0

    for pdf_path in pdf_files:
        output_path = target_dir / f"{pdf_path.stem}.md"
        try:
            pdf_to_section_markdown(pdf_path, output_path)
            converted += 1
            print(f"Converted: {pdf_path.name} -> {output_path.name}")
        except Exception as error:
            failed += 1
            print(f"Failed: {pdf_path.name}")
            print(f"Reason: {error}")

    print(f"\nPDF conversion done. Converted {converted} PDF files. Failed: {failed}")
    print(f"Markdown files saved under: {target_dir}")
    return converted, failed


# ---------------------------------------------------------------------------
# Stage 3: Structure/merge generated Markdown into existing paper Markdown
# ---------------------------------------------------------------------------


def normalize_title(title: str) -> str:
    """Normalize titles for deterministic and fuzzy matching."""
    title = title.strip()
    title = title.split("|", 1)[0].strip()
    title = title.strip('"').strip("'")
    title = title.lower()

    title = title.replace("–", "-").replace("—", "-")
    title = title.replace("β", "beta")
    title = title.replace("α", "alpha")
    title = title.replace("γ", "gamma")
    title = title.replace("δ", "delta")
    title = title.replace("μ", "mu")

    title = re.sub(r"[/:;,.()\[\]{}]", "", title)
    title = re.sub(r"[\"'‘’“”]", "", title)
    title = re.sub(r"[^\w\s-]", " ", title, flags=re.UNICODE)
    title = re.sub(r"\s+", " ", title)

    return title.strip()


def extract_title_from_paper_md(md_path: Path) -> str | None:
    """Extract a title from a Markdown metadata line such as `title: ...`."""
    text = md_path.read_text(encoding="utf-8", errors="replace")

    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.lower().startswith("title:"):
            title = line_stripped.split(":", 1)[1].strip()
            title = title.strip('"').strip("'")
            return title if title else None

    return None


def extract_title_from_generated_filename(md_path: Path) -> str:
    """Extract title part from generated Markdown filename."""
    stem = md_path.stem
    parts = re.split(r"\s+[–—-]\s+", stem)
    return parts[-1].strip() if len(parts) >= 3 else stem.strip()


def build_generated_markdown_index(generated_md_dir: Path) -> dict[str, Path]:
    """Build lookup: normalized generated title -> generated Markdown path."""
    index: dict[str, Path] = {}

    for md_path in sorted(generated_md_dir.glob("*.md")):
        title = extract_title_from_generated_filename(md_path)
        normalized = normalize_title(title)

        if normalized in index:
            print("WARNING: Duplicate generated title match:")
            print(f"  Existing: {index[normalized]}")
            print(f"  Duplicate: {md_path}")
            print("  Keeping existing one.")
            continue

        index[normalized] = md_path

    return index


def find_imported_at_cutoff(lines: list[str]) -> int | None:
    """Return the index after keeping exactly two lines after imported_at:."""
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("imported_at:"):
            return min(i + 3, len(lines))
    return None


def update_paper_markdown_file(paper_md_path: Path, generated_md_path: Path) -> None:
    """Replace everything after two lines after imported_at: with generated content."""
    paper_text = paper_md_path.read_text(encoding="utf-8", errors="replace")
    generated_text = generated_md_path.read_text(encoding="utf-8", errors="replace")

    paper_lines = paper_text.splitlines()
    cutoff = find_imported_at_cutoff(paper_lines)

    if cutoff is None:
        raise ValueError("No line starting with 'imported_at:' found.")

    kept_text = "\n".join(paper_lines[:cutoff]).rstrip()
    new_text = kept_text + "\n\n" + generated_text.strip() + "\n"
    paper_md_path.write_text(new_text, encoding="utf-8")


def find_prefix_match(
    normalized_paper_title: str,
    generated_index: dict[str, Path],
    min_prefix_length: int = 40,
) -> Path | None:
    """Match when one normalized title is a truncated prefix of the other."""
    for generated_title_key, generated_path in generated_index.items():
        shorter = min(normalized_paper_title, generated_title_key, key=len)
        longer = max(normalized_paper_title, generated_title_key, key=len)

        if len(shorter) >= min_prefix_length and longer.startswith(shorter):
            return generated_path

    return None


def find_best_fuzzy_match(
    normalized_paper_title: str,
    generated_index: dict[str, Path],
    min_score: float = 0.82,
) -> tuple[Path | None, float, str | None]:
    """
    Find the closest generated Markdown title by string similarity.

    Returns:
        (path, score, matched_key). path is None when best score is below min_score.
    """
    best_path: Path | None = None
    best_score = 0.0
    best_key: str | None = None

    for generated_title_key, generated_path in generated_index.items():
        score = SequenceMatcher(None, normalized_paper_title, generated_title_key).ratio()
        if score > best_score:
            best_score = score
            best_path = generated_path
            best_key = generated_title_key

    if best_score >= min_score:
        return best_path, best_score, best_key

    return None, best_score, best_key


def structure_paper_markdown_files(
    papers_dir: Path,
    generated_md_dir: Path,
    fuzzy_min_score: float = 0.82,
) -> dict[str, int]:
    """Update paper Markdown files with matching generated full-text Markdown."""
    if not papers_dir.exists():
        raise FileNotFoundError(f"Papers directory not found: {papers_dir}")
    if not generated_md_dir.exists():
        raise FileNotFoundError(f"Generated Markdown directory not found: {generated_md_dir}")

    generated_index = build_generated_markdown_index(generated_md_dir)

    if not generated_index:
        print(f"No generated Markdown files found in: {generated_md_dir}")
        return {"updated": 0, "skipped_no_title": 0, "skipped_no_match": 0, "failed": 0}

    updated = 0
    skipped_no_title = 0
    skipped_no_match = 0
    failed = 0

    for paper_md_path in sorted(papers_dir.glob("*.md")):
        try:
            paper_title = extract_title_from_paper_md(paper_md_path)

            if not paper_title:
                skipped_no_title += 1
                print(f"SKIP no title: {paper_md_path.name}")
                continue

            normalized_paper_title = normalize_title(paper_title)
            generated_md_path = generated_index.get(normalized_paper_title)

            if generated_md_path is None:
                generated_md_path = find_prefix_match(
                    normalized_paper_title,
                    generated_index,
                    min_prefix_length=40,
                )

            if generated_md_path is None:
                generated_md_path, score, matched_key = find_best_fuzzy_match(
                    normalized_paper_title,
                    generated_index,
                    min_score=fuzzy_min_score,
                )

                if generated_md_path is None:
                    skipped_no_match += 1
                    print("SKIP no generated Markdown match:")
                    print(f"  Paper file: {paper_md_path.name}")
                    print(f"  Title: {paper_title}")
                    print(f"  Best fuzzy score: {score:.3f}")
                    print(f"  Best generated title key: {matched_key}")
                    continue

            update_paper_markdown_file(paper_md_path, generated_md_path)
            updated += 1
            print("UPDATED:")
            print(f"  Target: {paper_md_path.name}")
            print(f"  Source: {generated_md_path.name}")

        except Exception as error:
            failed += 1
            print(f"FAILED: {paper_md_path.name}")
            print(f"Reason: {error}")

    print("\nStructuring done.")
    print(f"Updated: {updated}")
    print(f"Skipped, no title: {skipped_no_title}")
    print(f"Skipped, no match: {skipped_no_match}")
    print(f"Failed: {failed}")

    return {
        "updated": updated,
        "skipped_no_title": skipped_no_title,
        "skipped_no_match": skipped_no_match,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Stage 4: Combine paper Markdown files
# ---------------------------------------------------------------------------


def combine_markdown_files(source_dir: Path, output_file: Path) -> int:
    """Combine all Markdown files from source_dir into one Markdown output file."""
    if not source_dir.exists():
        raise FileNotFoundError(f"Markdown source directory not found: {source_dir}")

    markdown_files = sorted(source_dir.glob("*.md"))

    if not markdown_files:
        print(f"No Markdown files found in: {source_dir}")
        return 0

    combined_parts: list[str] = [
        "# Combined Literature Markdown",
        "",
        f"- Source folder: `{source_dir}`",
        f"- Number of files: {len(markdown_files)}",
        "",
    ]

    added = 0

    for index, md_path in enumerate(markdown_files, start=1):
        try:
            content = md_path.read_text(encoding="utf-8", errors="replace").strip()

            combined_parts.extend(
                [
                    "---",
                    "",
                    f"# Document {index}: {md_path.stem}",
                    "",
                    f"<!-- Source file: {md_path.name} -->",
                    "",
                    content,
                    "",
                ]
            )

            added += 1
            print(f"Added: {md_path.name}")

        except Exception as error:
            print(f"Failed: {md_path.name}")
            print(f"Reason: {error}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(combined_parts), encoding="utf-8")

    print(f"\nCombine done. Combined {added} Markdown files.")
    print("Output file:")
    print(output_file)
    return added


# ---------------------------------------------------------------------------
# CLI / Orchestration
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the combined Zotero PDF import, PDF-to-Markdown conversion, Markdown structuring, and Markdown combining pipeline."
    )

    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--zotero-storage-dir", type=Path, default=DEFAULT_ZOTERO_STORAGE_DIR)
    parser.add_argument("--pdf-dir", type=Path, default=None)
    parser.add_argument("--generated-md-dir", type=Path, default=None)
    parser.add_argument("--papers-dir", type=Path, default=None)
    parser.add_argument("--combined-output-file", type=Path, default=None)
    parser.add_argument("--fuzzy-min-score", type=float, default=0.82)

    parser.add_argument("--skip-import", action="store_true", help="Do not copy PDFs from Zotero storage.")
    parser.add_argument("--skip-convert", action="store_true", help="Do not convert PDFs to Markdown.")
    parser.add_argument("--skip-structure", action="store_true", help="Do not inject generated Markdown into paper Markdown files.")
    parser.add_argument("--skip-combine", action="store_true", help="Do not combine paper Markdown files.")

    return parser.parse_args()


def resolve_paths(args: argparse.Namespace) -> PipelinePaths:
    base_dir: Path = args.base_dir

    return PipelinePaths(
        zotero_storage_dir=args.zotero_storage_dir,
        pdf_dir=args.pdf_dir or base_dir / "Paper-PDF",
        generated_md_dir=args.generated_md_dir or base_dir / "Markdown",
        papers_dir=args.papers_dir or base_dir / "papers",
        combined_output_file=args.combined_output_file or base_dir / "combined_literature.md",
    )


def run_pipeline(
    base_dir: Path,
    zotero_storage_dir: Path,
    *,
    pdf_dir: Path | None = None,
    generated_md_dir: Path | None = None,
    papers_dir: Path | None = None,
    combined_output_file: Path | None = None,
    fuzzy_min_score: float = 0.82,
    skip_import: bool = False,
    skip_convert: bool = False,
    skip_structure: bool = False,
    skip_combine: bool = False,
) -> None:
    paths = PipelinePaths(
        zotero_storage_dir=Path(zotero_storage_dir),
        pdf_dir=Path(pdf_dir) if pdf_dir else Path(base_dir) / "Paper-PDF",
        generated_md_dir=Path(generated_md_dir) if generated_md_dir else Path(base_dir) / "Markdown",
        papers_dir=Path(papers_dir) if papers_dir else Path(base_dir) / "papers",
        combined_output_file=(
            Path(combined_output_file)
            if combined_output_file
            else Path(base_dir) / "combined_literature.md"
        ),
    )

    print("Using paths:")
    print(f"  Zotero storage:      {paths.zotero_storage_dir}")
    print(f"  PDF directory:       {paths.pdf_dir}")
    print(f"  Generated Markdown:  {paths.generated_md_dir}")
    print(f"  Papers directory:    {paths.papers_dir}")
    print(f"  Combined output:     {paths.combined_output_file}")
    print()

    if not skip_import:
        import_pdfs_from_zotero(paths.zotero_storage_dir, paths.pdf_dir)
        print()

    if not skip_convert:
        convert_pdfs_to_markdown(paths.pdf_dir, paths.generated_md_dir)
        print()

    if not skip_structure:
        structure_paper_markdown_files(
            paths.papers_dir,
            paths.generated_md_dir,
            fuzzy_min_score=fuzzy_min_score,
        )
        print()

    if not skip_combine:
        combine_markdown_files(paths.papers_dir, paths.combined_output_file)


def main() -> None:
    args = parse_args()

    run_pipeline(
        base_dir=args.base_dir,
        zotero_storage_dir=args.zotero_storage_dir,
        pdf_dir=args.pdf_dir,
        generated_md_dir=args.generated_md_dir,
        papers_dir=args.papers_dir,
        combined_output_file=args.combined_output_file,
        fuzzy_min_score=args.fuzzy_min_score,
        skip_import=args.skip_import,
        skip_convert=args.skip_convert,
        skip_structure=args.skip_structure,
        skip_combine=args.skip_combine,
    )


if __name__ == "__main__":
    main()
