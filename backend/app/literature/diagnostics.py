from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from backend.app.literature.literature_types import ExtractionDiagnostics


def generate_diagnostics(
    raw_text: str,
    cleaned_text: str,
    pdf_path: Path | None,
    page_count: int | None,
    cleanup_warnings: List[str],
    cleanup_rule_counts: dict[str, int] | None = None,
    errors: List[str] | None = None,
) -> ExtractionDiagnostics:
    """Generate detailed extraction-quality diagnostics for a processed paper."""
    diagnostics = ExtractionDiagnostics()
    diagnostics.pdf_found = pdf_path is not None and pdf_path.exists()
    diagnostics.page_count = page_count
    diagnostics.extracted_character_count = len(raw_text)
    diagnostics.cleaned_character_count = len(cleaned_text)

    # Detect title
    title_match = re.search(r"^#\s+(.+)$", cleaned_text, re.MULTILINE)
    diagnostics.title_detected = title_match is not None

    # Detect abstract
    diagnostics.abstract_detected = re.search(r"(?i)abstract", cleaned_text) is not None

    # Count sections (headings starting with ## or ###)
    sections = re.findall(r"^##{1,2}\s+.*$", cleaned_text, re.MULTILINE)
    diagnostics.number_of_sections = len(sections)

    # Detect reference section
    diagnostics.reference_section_detected = re.search(
        r"(?im)^\s*(references|bibliography|literature cited)\s*$", cleaned_text
    ) is not None

    # Detect possible scanned document
    # Suspected if we have pages but extremely low character count (< 200 chars total)
    if (page_count or 0) > 0 and len(raw_text.strip()) < 200:
        diagnostics.possible_scanned_document = True

    # Detect duplicate-text warnings (e.g. repeated paragraph extracts)
    lines = [line.strip() for line in cleaned_text.split("\n") if len(line.strip()) > 60]
    duplicate_lines = set()
    for line in lines:
        if lines.count(line) > 1:
            duplicate_lines.add(line[:50] + "...")
    diagnostics.duplicate_text_warnings = list(duplicate_lines)

    # Set extraction success
    diagnostics.errors = errors or []
    diagnostics.extraction_success = bool(cleaned_text.strip()) and not diagnostics.errors

    # Set cleanup warnings
    diagnostics.cleanup_warnings = list(cleanup_warnings)
    if cleanup_rule_counts:
        diagnostics.cleanup_warnings.extend(
            f"cleanup:{rule} removed {count} line(s)"
            for rule, count in sorted(cleanup_rule_counts.items())
        )

    # Determine final usability status
    if not diagnostics.extraction_success:
        diagnostics.final_usability_status = "failed"
    elif diagnostics.possible_scanned_document or diagnostics.extracted_character_count < 500:
        diagnostics.final_usability_status = "requires_manual_review"
    elif len(diagnostics.duplicate_text_warnings) > 3 or cleanup_warnings:
        diagnostics.final_usability_status = "usable_with_warnings"
    else:
        diagnostics.final_usability_status = "usable"

    return diagnostics


def save_diagnostics_report(report_path: Path, diagnostics_dict: Dict[str, Any]) -> None:
    """Save or append diagnostics to the extraction report JSON file."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    existing_reports = {}
    if report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                existing_reports = json.load(f)
        except Exception:
            existing_reports = {}

    # Update or add the paper diagnostics
    paper_id = diagnostics_dict.get("paper_id") or "unknown"
    existing_reports[paper_id] = diagnostics_dict

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(existing_reports, f, indent=2, ensure_ascii=False)
