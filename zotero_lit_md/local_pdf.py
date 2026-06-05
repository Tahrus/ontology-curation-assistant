from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from zotero_lit_md.text_cleaning import remove_repeating_headers_footers


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    char_count: int


@dataclass
class ExtractedPdf:
    pdf_path: Path
    pdf_filename: str
    page_count: int
    pages: list[ExtractedPage]
    total_char_count: int
    extraction_method: str
    extraction_status: str
    warnings: list[str] = field(default_factory=list)
    detected_layout: str = "unknown"


@dataclass
class LocalMarkdownResult:
    pdf: ExtractedPdf
    markdown_path: Path | None


def find_pdfs(folder: Path, recursive: bool = True) -> list[Path]:
    if recursive:
        return _dedupe_paths(list(folder.rglob("*.pdf")) + list(folder.rglob("*.PDF")))
    return _dedupe_paths(list(folder.glob("*.pdf")) + list(folder.glob("*.PDF")))


def extract_pdf_text(pdf_path: Path) -> ExtractedPdf:
    pages: list[ExtractedPage] = []
    warnings: list[str] = []
    try:
        import fitz

        with fitz.open(pdf_path) as document:
            raw_pages = []
            for page in document:
                raw_pages.append(page.get_text("text") or "")
            cleaned_pages = _clean_pages(raw_pages)
            for page_number, text in enumerate(cleaned_pages, start=1):
                pages.append(ExtractedPage(page_number=page_number, text=text, char_count=len(text)))
    except Exception as exc:
        return ExtractedPdf(
            pdf_path=pdf_path,
            pdf_filename=pdf_path.name,
            page_count=0,
            pages=[],
            total_char_count=0,
            extraction_method="PyMuPDF",
            extraction_status="failed",
            warnings=[f"PyMuPDF could not open or extract the PDF: {exc}"],
        )

    total_chars = sum(page.char_count for page in pages)
    status = "complete" if total_chars >= 500 else "partial_or_empty"
    if status == "partial_or_empty":
        warnings.append("Extracted characters below 500; PDF may be scanned, encrypted, or have a sparse text layer.")
    return ExtractedPdf(
        pdf_path=pdf_path,
        pdf_filename=pdf_path.name,
        page_count=len(pages),
        pages=pages,
        total_char_count=total_chars,
        extraction_method="PyMuPDF",
        extraction_status=status,
        warnings=warnings,
        detected_layout=_detect_layout([page.text for page in pages]),
    )


def write_extracted_pdf_markdown(
    extracted: ExtractedPdf,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _available_output_path(output_dir, sanitize_pdf_stem(extracted.pdf_path.stem), overwrite=overwrite)
    path.write_text(render_extracted_pdf_markdown(extracted), encoding="utf-8")
    return path


def render_extracted_pdf_markdown(extracted: ExtractedPdf) -> str:
    title = extracted.pdf_path.stem
    full_text = "\n\n".join(page.text for page in extracted.pages if page.text)
    body = convert_headings(full_text)
    abstract = _detect_section_text(full_text, "abstract") or "_Abstract not detected in extracted PDF text._"
    keywords = _detect_keywords(full_text) or "_Keywords not detected in extracted PDF text._"
    doi = _detect_doi(full_text)
    references = "yes" if re.search(r"(?im)^references\s*$", full_text) else "unknown"
    warnings = extracted.warnings or [""]
    chunks = build_local_retrieval_chunks(extracted)
    return "\n".join(
        [
            f"# {title}",
            "",
            "## LLM-ready full-text Markdown",
            "",
            "This Markdown file was generated from a local PDF file. Images were omitted. Extracted figure captions, table text, equations, references, and article body text are retained where the PDF text layer exposed them. The layout was converted into a single reading order for LLM/RAG ingestion.",
            "",
            "## Minimal metadata",
            "",
            f"- **Title:** {title}",
            f"- **DOI:** {doi}",
            "- **Citation:** ",
            "- **Source:** local PDF",
            f"- **PDF filename:** {extracted.pdf_filename}",
            f"- **PDF path:** {extracted.pdf_path.resolve()}",
            "- **Images:** omitted",
            f"- **Extraction status:** {extracted.extraction_status}",
            "",
            "## Extraction diagnostics",
            "",
            f"- **PDF pages:** {extracted.page_count}",
            f"- **Extracted characters:** {extracted.total_char_count}",
            f"- **Text extraction method:** {extracted.extraction_method}",
            f"- **Detected layout:** {extracted.detected_layout}",
            "- **Tables extracted:** unknown",
            "- **Equations extracted:** unknown",
            f"- **References extracted:** {references}",
            "- **Warnings:**",
            *[f"  - {warning}" for warning in warnings],
            "",
            "## Abstract",
            "",
            abstract,
            "",
            "## Keywords",
            "",
            keywords,
            "",
            "## Paper body",
            "",
            body,
            "",
            "## Retrieval chunks",
            "",
            *[_render_chunk(chunk) for chunk in chunks],
            "",
            "## Notes for LLM use",
            "",
            "- This file contains extracted PDF text.",
            "- Images are omitted.",
            "- Figure captions are included only if they were present in the PDF text layer.",
            "- Table text is included only if it was exposed by the PDF text layer.",
            "- Equations are retained where exposed by the PDF text layer.",
            "- No missing text was invented.",
            "- Retrieval chunks are provided for RAG indexing.",
            "",
        ]
    )


def sanitize_pdf_stem(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]+', "_", value).strip()
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized or "untitled"


def convert_headings(text: str) -> str:
    lines: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        figure = re.match(r"^(?:fig|figure)\.?\s+(\d+)\.?\s*(.*)$", line, flags=re.IGNORECASE)
        if figure:
            lines.extend([f"### Figure {figure.group(1)}", "", figure.group(2).strip()])
            continue
        table = re.match(r"^table\s+(\d+)\.?\s*(.*)$", line, flags=re.IGNORECASE)
        if table:
            lines.extend([f"### Table {table.group(1)}", "", table.group(2).strip()])
            continue
        numbered = re.match(r"^(\d+(?:\.\d+){0,3})\.?\s+(.+)$", line)
        if numbered:
            level = min(2 + numbered.group(1).count("."), 4)
            lines.append(f"{'#' * level} {line}")
            continue
        if _is_common_heading(line):
            lines.append(f"## {line}")
            continue
        lines.append(line)
    return _squash_blank_lines("\n".join(lines))


def build_local_retrieval_chunks(extracted: ExtractedPdf, *, target_tokens: int = 1000, max_tokens: int = 1500) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    current: list[str] = []
    start_page: int | None = None
    current_section = "unknown"
    counter = 1
    for page in extracted.pages:
        for paragraph in [p.strip() for p in re.split(r"\n\s*\n", page.text) if p.strip()]:
            heading = _heading_label(paragraph)
            if heading:
                current_section = heading
            candidate = "\n\n".join([*current, paragraph])
            if current and approx_tokens(candidate) > max_tokens:
                chunks.append(_chunk(counter, current, start_page, page.page_number, current_section))
                counter += 1
                current = [paragraph]
                start_page = page.page_number
            else:
                if not current:
                    start_page = page.page_number
                current.append(paragraph)
            if approx_tokens("\n\n".join(current)) >= target_tokens:
                chunks.append(_chunk(counter, current, start_page, page.page_number, current_section))
                counter += 1
                current = []
                start_page = None
    if current:
        end_page = extracted.pages[-1].page_number if extracted.pages else start_page
        chunks.append(_chunk(counter, current, start_page, end_page, current_section))
    return chunks


def approx_tokens(text: str) -> int:
    return max(1, round(len(text or "") / 4))


def _chunk(counter: int, paragraphs: list[str], start_page: int | None, end_page: int | None, section: str) -> dict[str, object]:
    text = "\n\n".join(paragraphs)
    return {
        "id": f"{counter:03d}",
        "section": section or "unknown",
        "page_start": start_page,
        "page_end": end_page,
        "approx_tokens": approx_tokens(text),
        "chunk_type": _chunk_type(section),
        "key_terms": _key_terms(text),
        "text": text,
    }


def _render_chunk(chunk: dict[str, object]) -> str:
    pages = _page_range(chunk["page_start"], chunk["page_end"])
    terms = ", ".join(chunk["key_terms"]) if isinstance(chunk["key_terms"], list) else ""
    return "\n".join(
        [
            f"### Chunk {chunk['id']}",
            "",
            f"- **Source section:** {chunk['section']}",
            f"- **Pages:** {pages}",
            f"- **Approx tokens:** {chunk['approx_tokens']}",
            f"- **Chunk type:** {chunk['chunk_type']}",
            f"- **Key terms:** {terms}",
            "",
            str(chunk["text"]),
            "",
        ]
    )


def _clean_pages(page_texts: list[str]) -> list[str]:
    cleaned = remove_repeating_headers_footers(page_texts)
    return [_squash_blank_lines(text) for text in cleaned]


def _squash_blank_lines(text: str) -> str:
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text or "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _available_output_path(output_dir: Path, stem: str, *, overwrite: bool) -> Path:
    candidate = output_dir / f"{stem}.md"
    if overwrite or not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = output_dir / f"{stem}_{counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1


def _detect_layout(page_texts: list[str]) -> str:
    lines = [line.strip() for text in page_texts for line in text.splitlines() if line.strip()]
    if not lines:
        return "unknown"
    short_ratio = sum(1 for line in lines if 20 <= len(line) <= 65) / len(lines)
    if short_ratio > 0.65:
        return "two-column"
    if short_ratio < 0.35:
        return "single-column"
    return "mixed"


def _detect_doi(text: str) -> str:
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text or "", flags=re.IGNORECASE)
    return match.group(0).rstrip(".") if match else ""


def _detect_section_text(text: str, heading: str) -> str:
    pattern = rf"(?is)\b{re.escape(heading)}\b\s*(.+?)(?=\n(?:keywords|1\.?\s+introduction|introduction|references)\b|$)"
    match = re.search(pattern, text or "")
    return _squash_blank_lines(match.group(1)) if match else ""


def _detect_keywords(text: str) -> str:
    match = re.search(r"(?is)\bkeywords?\b[:\s]*(.+?)(?=\n(?:1\.?\s+introduction|introduction|abstract|references)\b|$)", text or "")
    return _squash_blank_lines(match.group(1)) if match else ""


def _is_common_heading(line: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", "", line.casefold()).strip()
    return normalized in {
        "abstract",
        "keywords",
        "references",
        "data availability",
        "declaration of competing interest",
        "credit authorship contribution statement",
        "acknowledgments",
        "acknowledgements",
        "appendix a supplementary data",
        "supplementary data",
        "funding",
        "author contributions",
        "conclusion",
        "conclusions",
        "discussion",
        "results",
        "methods",
        "materials and methods",
        "introduction",
    }


def _heading_label(text: str) -> str:
    first_line = (text or "").splitlines()[0].strip() if text else ""
    if re.match(r"^#+\s+", first_line):
        return re.sub(r"^#+\s+", "", first_line)
    if _is_common_heading(first_line) or re.match(r"^\d+(?:\.\d+){0,3}\.?\s+", first_line):
        return first_line
    return ""


def _chunk_type(section: str) -> str:
    normalized = (section or "").casefold()
    if "abstract" in normalized:
        return "abstract"
    if "introduction" in normalized:
        return "introduction"
    if "method" in normalized or "material" in normalized:
        return "methods"
    if "result" in normalized:
        return "results"
    if "discussion" in normalized:
        return "discussion"
    if "conclusion" in normalized:
        return "conclusion"
    if "reference" in normalized:
        return "references"
    if "table" in normalized:
        return "table"
    if "fig" in normalized:
        return "figure_caption"
    return "unknown"


def _key_terms(text: str, *, limit: int = 10) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{4,}", text or "")
    ignored = {"which", "there", "their", "these", "those", "using", "paper", "study"}
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for word in words:
        key = word.casefold()
        if key in ignored:
            continue
        counts[key] = counts.get(key, 0) + 1
        display.setdefault(key, word)
    return [display[key] for key, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _page_range(start: object, end: object) -> str:
    if start is None and end is None:
        return ""
    if end is None or start == end:
        return str(start)
    return f"{start}-{end}"


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in paths:
        unique.setdefault(str(path.resolve()).casefold(), path)
    return sorted(unique.values())
