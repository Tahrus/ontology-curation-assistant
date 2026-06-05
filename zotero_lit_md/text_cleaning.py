from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path


SECTION_KEYWORDS = {
    "abstract",
    "introduction",
    "background",
    "materials and methods",
    "methods",
    "methodology",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
    "acknowledgments",
    "acknowledgements",
    "funding",
    "declarations",
    "conflicts of interest",
    "data availability",
    "supplementary material",
}


def normalize_whitespace(text: str) -> str:
    """Normalize spacing without stripping scientific symbols or notation."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_repeating_headers_footers(page_texts: list[str], *, max_line_length: int = 120) -> list[str]:
    """Remove repeated short lines and standalone page numbers from page-level text."""
    stripped_pages = [page.replace("\r\n", "\n").replace("\r", "\n") for page in page_texts]
    line_counts: Counter[str] = Counter()
    for page in stripped_pages:
        candidates = [line.strip() for line in page.splitlines() if line.strip()]
        for line in set(candidates[:4] + candidates[-4:]):
            if len(line) <= max_line_length:
                line_counts[line.casefold()] += 1

    repeated = {
        line
        for line, count in line_counts.items()
        if count >= 2 and count >= max(2, len(stripped_pages) // 2)
    }
    cleaned_pages = []
    for page in stripped_pages:
        kept = []
        for line in page.splitlines():
            clean = line.strip()
            if re.fullmatch(r"(?:page\s*)?\d+", clean, flags=re.IGNORECASE):
                continue
            if clean.casefold() in repeated:
                continue
            kept.append(line)
        cleaned_pages.append(normalize_whitespace("\n".join(kept)))
    return cleaned_pages


def safe_filename_part(value: str, *, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-").lower()
    return (normalized[:max_length].strip("-") or "untitled")


def paper_markdown_filename(
    *,
    year: str,
    lead_author: str,
    title: str,
    zotero_key: str = "",
    existing: set[str] | None = None,
) -> str:
    base = "_".join(
        part
        for part in [
            safe_filename_part(year, max_length=8),
            safe_filename_part(lead_author, max_length=32),
            safe_filename_part(title, max_length=64),
        ]
        if part and part != "untitled"
    ) or safe_filename_part(title)
    filename = f"{base}.md"
    if existing and filename in existing and zotero_key:
        filename = f"{base}_{safe_filename_part(zotero_key, max_length=16)}.md"
    return filename


def detect_heading_level(line: str) -> int | None:
    stripped = line.strip()
    numbered = re.match(r"^(\d+(?:\.\d+){0,3})\.?\s+(.+)$", stripped)
    if numbered:
        return min(2 + numbered.group(1).count("."), 4)
    normalized = re.sub(r"[^a-z0-9 ]+", "", stripped.casefold())
    if normalized in SECTION_KEYWORDS:
        return 2
    if re.match(r"^(figure|fig)\.?\s+\d+", stripped, flags=re.IGNORECASE):
        return 3
    if re.match(r"^table\s+\d+", stripped, flags=re.IGNORECASE):
        return 3
    return None


def chunk_type_for_heading(heading: str) -> str:
    normalized = heading.casefold()
    if "abstract" in normalized:
        return "abstract"
    if "introduction" in normalized or "background" in normalized:
        return "introduction"
    if "method" in normalized or "material" in normalized:
        return "method"
    if "result" in normalized:
        return "result"
    if "discussion" in normalized:
        return "discussion"
    if "conclusion" in normalized:
        return "conclusion"
    if "reference" in normalized:
        return "reference"
    if "table" in normalized:
        return "table"
    if "figure" in normalized or "fig." in normalized:
        return "figure_caption"
    if any(word in normalized for word in ["declaration", "funding", "availability", "conflict"]):
        return "declaration"
    return "other"


def path_text(path: Path | str) -> str:
    return str(path).replace("\\", "/")
