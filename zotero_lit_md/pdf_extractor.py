from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from zotero_lit_md.schema import ExtractionDiagnostics, ExtractedPaper, PageText, PaperMetadata, SectionBlock
from zotero_lit_md.text_cleaning import detect_heading_level, normalize_whitespace, remove_repeating_headers_footers


def extract_pdf_to_paper(pdf_path: Path, metadata: PaperMetadata, *, ocr: bool = False) -> ExtractedPaper:
    diagnostics = ExtractionDiagnostics()
    pages: list[PageText] = []
    try:
        pages, diagnostics = _extract_with_pymupdf(pdf_path, diagnostics)
    except Exception as exc:
        diagnostics.warnings.append(f"PyMuPDF extraction failed: {exc}")
        pages, diagnostics = _extract_with_pypdf(pdf_path, diagnostics)

    if ocr:
        diagnostics.warnings.append("OCR was requested, but OCR support is optional and not implemented in this build.")

    if not pages:
        diagnostics.extraction_status = "failed"
        return ExtractedPaper(metadata=metadata, diagnostics=diagnostics, source_pdf=pdf_path)

    cleaned = remove_repeating_headers_footers([page.text for page in pages])
    pages = [PageText(page.page_number, text) for page, text in zip(pages, cleaned, strict=False)]
    diagnostics.pdf_pages = len(pages)
    diagnostics.detected_layout = _detect_layout_from_pages([page.text for page in pages])
    body = "\n\n".join(page.text for page in pages if page.text)
    sections = parse_sections_from_pages(pages)
    diagnostics.references_extracted = "yes" if re.search(r"(?im)^references\s*$", body) else "no"
    diagnostics.extracted_characters = len(body)
    diagnostics.extraction_status = "complete" if body.strip() else "failed"
    if diagnostics.warnings and diagnostics.extraction_status == "complete":
        diagnostics.extraction_status = "warning"
    return ExtractedPaper(metadata=metadata, diagnostics=diagnostics, pages=pages, sections=sections, source_pdf=pdf_path)


def parse_sections_from_pages(pages: list[PageText]) -> list[SectionBlock]:
    sections: list[SectionBlock] = []
    stack: list[SectionBlock] = []
    current = SectionBlock(heading="Paper body", level=2, page_start=pages[0].page_number if pages else None)
    sections.append(current)
    stack = [current]
    for page in pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            level = detect_heading_level(line)
            if level is not None and len(line) <= 140:
                section = SectionBlock(heading=_canonical_heading(line), level=level, page_start=page.page_number, page_end=page.page_number)
                while stack and stack[-1].level >= level:
                    stack.pop()
                if stack:
                    stack[-1].subsections.append(section)
                else:
                    sections.append(section)
                stack.append(section)
                current = section
                continue
            current.text = f"{current.text}\n{line}".strip()
            current.page_end = page.page_number
    return [section for section in sections if section.text or section.subsections]


def _extract_with_pymupdf(pdf_path: Path, diagnostics: ExtractionDiagnostics) -> tuple[list[PageText], ExtractionDiagnostics]:
    import fitz

    pages: list[PageText] = []
    diagnostics.text_extraction_method = "pymupdf"
    with fitz.open(pdf_path) as document:
        if document.is_encrypted:
            diagnostics.warnings.append("PDF is encrypted; attempting text extraction without decryption.")
        for index, page in enumerate(document, start=1):
            blocks = page.get_text("blocks")
            pages.append(PageText(index, _blocks_to_reading_order(blocks, float(page.rect.width))))
    return pages, diagnostics


def _extract_with_pypdf(pdf_path: Path, diagnostics: ExtractionDiagnostics) -> tuple[list[PageText], ExtractionDiagnostics]:
    from pypdf import PdfReader

    pages: list[PageText] = []
    diagnostics.text_extraction_method = "fallback"
    reader = PdfReader(str(pdf_path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            diagnostics.warnings.append(f"PDF is encrypted and could not be decrypted: {exc}")
            return pages, diagnostics
    for index, page in enumerate(reader.pages, start=1):
        pages.append(PageText(index, normalize_whitespace(page.extract_text() or "")))
    return pages, diagnostics


def _blocks_to_reading_order(blocks: list[Any], page_width: float) -> str:
    text_blocks = [
        block
        for block in blocks
        if len(block) >= 5 and isinstance(block[4], str) and block[4].strip()
    ]
    full_width = []
    left = []
    right = []
    midpoint = page_width / 2
    for block in text_blocks:
        x0, y0, x1, _y1, text = block[:5]
        width = x1 - x0
        if width > page_width * 0.65:
            full_width.append(block)
        elif x0 < midpoint:
            left.append(block)
        else:
            right.append(block)
    ordered = sorted(full_width, key=lambda b: (b[1], b[0]))
    if left and right:
        ordered.extend(sorted(left, key=lambda b: (b[1], b[0])))
        ordered.extend(sorted(right, key=lambda b: (b[1], b[0])))
    else:
        ordered.extend(sorted([*left, *right], key=lambda b: (b[1], b[0])))
    return normalize_whitespace("\n".join(str(block[4]) for block in ordered))


def _detect_layout_from_pages(page_texts: list[str]) -> str:
    joined = "\n".join(page_texts)
    if not joined.strip():
        return "unknown"
    short_line_ratio = sum(1 for line in joined.splitlines() if 20 <= len(line.strip()) <= 65) / max(1, len(joined.splitlines()))
    return "two-column" if short_line_ratio > 0.55 else "single-column"


def _canonical_heading(line: str) -> str:
    stripped = line.strip()
    if re.match(r"^(fig|figure)\.?\s+\d+", stripped, flags=re.IGNORECASE):
        number = re.search(r"\d+", stripped)
        return f"Figure {number.group(0)}" if number else stripped
    if re.match(r"^table\s+\d+", stripped, flags=re.IGNORECASE):
        number = re.search(r"\d+", stripped)
        return f"Table {number.group(0)}" if number else stripped
    return stripped
