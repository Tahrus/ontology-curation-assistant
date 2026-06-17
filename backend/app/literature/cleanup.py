from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, List, Tuple


@dataclass(frozen=True)
class CleanupRule:
    name: str
    pattern: re.Pattern[str]
    max_line_length: int = 220


@dataclass
class CleanupResult:
    cleaned_text: str
    removed_lines: List[str] = field(default_factory=list)
    rule_counts: dict[str, int] = field(default_factory=dict)
    examples: dict[str, List[str]] = field(default_factory=dict)


# Explicit line-level rules for common PDF extraction boilerplate/artifacts.
# DOI-only or DOI-containing scientific lines are intentionally not removed.
BOILERPLATE_RULES = [
    CleanupRule("open_access_published_on", re.compile(r"^\s*open access article\.\s+published on\b.*$", re.IGNORECASE)),
    CleanupRule("view_article_online", re.compile(r"^\s*view article online\b.*$", re.IGNORECASE)),
    CleanupRule("downloaded_on", re.compile(r"^\s*downloaded on\b.*$", re.IGNORECASE)),
    CleanupRule("downloaded_from", re.compile(r"^\s*downloaded from\b.*$", re.IGNORECASE)),
    CleanupRule("publisher_navigation", re.compile(r"^\s*(article|journal|issue|volume)\s+navigation\s*$", re.IGNORECASE)),
    CleanupRule("copyright_notice", re.compile(r"^\s*(?:copyright\s*)?(?:\(c\)|©)\s*\d{4}\b.*$", re.IGNORECASE)),
    CleanupRule("all_rights_reserved", re.compile(r"^\s*all rights reserved\.?\s*$", re.IGNORECASE)),
    CleanupRule("known_publisher_footer", re.compile(r"^\s*(?:rsc|elsevier|springer nature|wiley|acs)\s+.*(?:registered charity|all rights reserved|published by)\b.*$", re.IGNORECASE)),
]

REFERENCE_SECTIONS = [
    re.compile(r"(?im)^\s*references\s*$"),
    re.compile(r"(?im)^\s*bibliography\s*$"),
    re.compile(r"(?im)^\s*literature cited\s*$"),
]


def clean_line_text(line: str) -> tuple[str, str | None]:
    """Clean isolated line of text from common publisher boilerplate and layout noise."""
    stripped = line.strip()
    if not stripped:
        return "", None

    # Remove isolated page numbers
    if re.fullmatch(r"(?:page\s*)?\d+", stripped, flags=re.IGNORECASE):
        return "", "isolated_page_number"

    # Check for general boilerplate
    for rule in BOILERPLATE_RULES:
        if len(stripped) <= rule.max_line_length and rule.pattern.search(stripped):
            return "", rule.name

    return stripped, None


def clean_page_text(text: str) -> Tuple[str, List[str]]:
    """Clean page text and return cleaned text plus list of flagged removed lines."""
    result = clean_page_text_with_report(text)
    return result.cleaned_text, result.removed_lines


def clean_page_text_with_report(text: str) -> CleanupResult:
    """Clean page text with rule counts and examples for provenance reports."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned_lines = []
    removed_lines = []
    rule_counts: Counter[str] = Counter()
    examples: defaultdict[str, list[str]] = defaultdict(list)

    for line in lines:
        cleaned, rule_name = clean_line_text(line)
        if cleaned:
            cleaned_lines.append(cleaned)
        else:
            if line.strip():
                removed_lines.append(line.strip())
                rule_counts[rule_name or "blank_or_whitespace"] += 1
                if len(examples[rule_name or "blank_or_whitespace"]) < 5:
                    examples[rule_name or "blank_or_whitespace"].append(line.strip())

    cleaned_text = "\n".join(cleaned_lines)
    # Fix hyphens at end of lines
    cleaned_text = re.sub(r"(\w)-\n(\w)", r"\1\2", cleaned_text)
    # Normalize whitespaces
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)

    return CleanupResult(
        cleaned_text=cleaned_text.strip(),
        removed_lines=removed_lines,
        rule_counts=dict(rule_counts),
        examples=dict(examples),
    )


def get_page_reading_order(page: Any) -> str:
    """Extract block-order text from a PyMuPDF page without claiming reliable layout repair."""
    blocks = page.get_text("blocks")
    if not blocks:
        return ""

    # Filter out empty text blocks or invalid blocks
    text_blocks = [
        block for block in blocks
        if len(block) >= 5 and isinstance(block[4], str) and block[4].strip()
    ]

    page_width = float(page.rect.width)
    midpoint = page_width / 2.0

    full_width = []
    left = []
    right = []

    for block in text_blocks:
        x0, y0, x1, y1, text = block[:5]
        width = x1 - x0

        # Blocks spanning more than 65% of the page are treated as full width (e.g. titles, abstracts)
        if width > page_width * 0.65:
            full_width.append(block)
        elif x0 < midpoint:
            left.append(block)
        else:
            right.append(block)

    # This is a best-effort ordering only; diagnostics flag likely reading-order issues later.
    ordered_blocks = sorted(full_width, key=lambda b: (b[1], b[0]))
    
    # Sort left and right columns
    left_sorted = sorted(left, key=lambda b: (b[1], b[0]))
    right_sorted = sorted(right, key=lambda b: (b[1], b[0]))

    ordered_blocks.extend(left_sorted)
    ordered_blocks.extend(right_sorted)

    text_parts = []
    for block in ordered_blocks:
        text_parts.append(block[4].strip())

    return "\n\n".join(text_parts)


def separate_references(text: str) -> Tuple[str, str]:
    """Separate reference list from the main body content using common section titles.
    
    Returns (main_body, references_body).
    """
    lines = text.split("\n")
    split_index = None

    for i, line in enumerate(lines):
        for pattern in REFERENCE_SECTIONS:
            if pattern.match(line):
                # Found reference section
                split_index = i
                break
        if split_index is not None:
            break

    if split_index is not None:
        main_body = "\n".join(lines[:split_index]).strip()
        references_body = "\n".join(lines[split_index:]).strip()
        return main_body, references_body

    return text.strip(), ""


def detect_formatting_anomalies(raw_text: str, cleaned_text: str) -> List[str]:
    """Detect potential anomalies in the text layout or extraction quality."""
    warnings = []

    if not raw_text.strip():
        warnings.append("Empty raw document text.")
        return warnings

    if len(cleaned_text.strip()) < 1000:
        warnings.append("Extremely low character count after cleanup.")

    # Check for possible scanned/image-only PDF (no text or very short compared to standard pages)
    # standard page is 1500-3000 chars, if total text is < 200 chars and pdf has multiple pages
    if len(raw_text.strip()) < 200:
        warnings.append("Scanned or image-only PDF document suspected.")

    # Check for abstract section
    if not re.search(r"(?i)abstract", cleaned_text):
        warnings.append("Abstract section not detected.")

    # Check for section headings
    section_count = len(re.findall(r"^##\s+.*$", cleaned_text, re.MULTILINE))
    if section_count == 0:
        warnings.append("No main Markdown section headings detected.")

    # Check for references section
    references_found = False
    for pattern in REFERENCE_SECTIONS:
        if pattern.search(cleaned_text):
            references_found = True
            break
    if not references_found:
        warnings.append("References section not detected.")

    # Check for suspiciously repeated text blocks
    # e.g., paragraph copies repeating
    lines = [line.strip() for line in cleaned_text.split("\n") if len(line.strip()) > 50]
    duplicate_lines = set()
    for line in lines:
        if lines.count(line) > 1:
            duplicate_lines.add(line[:50] + "...")
    if duplicate_lines:
        warnings.append(f"Suspiciously repeated paragraphs/lines detected: {list(duplicate_lines)[:3]}")

    return warnings
