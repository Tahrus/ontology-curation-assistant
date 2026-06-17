from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional


@dataclass
class PaperMetadata:
    """Stable metadata representing the YAML front matter of a cleaned paper."""
    paper_id: str
    zotero_key: str = ""
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: str = ""
    doi: str = ""
    source_pdf: str = ""
    raw_markdown: str = ""
    source_collection: str = ""
    extraction_method: str = ""
    extraction_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cleanup_version: str = ""
    extraction_quality: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "zotero_key": self.zotero_key,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "doi": self.doi,
            "source_pdf": self.source_pdf,
            "raw_markdown": self.raw_markdown,
            "source_collection": self.source_collection,
            "extraction_method": self.extraction_method,
            "extraction_date": self.extraction_date,
            "cleanup_version": self.cleanup_version,
            "extraction_quality": self.extraction_quality,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperMetadata:
        return cls(
            paper_id=data.get("paper_id") or data.get("id") or "",
            zotero_key=data.get("zotero_key") or data.get("zotero_key") or "",
            title=data.get("title") or "",
            authors=data.get("authors") or [],
            year=data.get("year"),
            journal=data.get("journal") or "",
            doi=data.get("doi") or "",
            source_pdf=data.get("source_pdf") or "",
            raw_markdown=data.get("raw_markdown") or data.get("source_pdf_markdown") or "",
            source_collection=data.get("source_collection") or "",
            extraction_method=data.get("extraction_method") or "",
            extraction_date=data.get("extraction_date") or datetime.now(timezone.utc).isoformat(),
            cleanup_version=data.get("cleanup_version") or "",
            extraction_quality=data.get("extraction_quality") or "unknown",
        )


@dataclass
class CleanupReport:
    """Audit report for deterministic extraction artifact cleanup."""
    raw_character_count: int = 0
    cleaned_character_count: int = 0
    removed_lines_count: int = 0
    rule_counts: dict[str, int] = field(default_factory=dict)
    examples: dict[str, List[str]] = field(default_factory=dict)
    removed_patterns: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_character_count": self.raw_character_count,
            "cleaned_character_count": self.cleaned_character_count,
            "removed_lines_count": self.removed_lines_count,
            "rule_counts": self.rule_counts,
            "examples": self.examples,
            "removed_patterns": self.removed_patterns,
            "warnings": self.warnings,
        }


@dataclass
class ExtractionDiagnostics:
    """Detailed quality diagnostic record for an imported paper."""
    pdf_found: bool = False
    page_count: Optional[int] = None
    extracted_character_count: int = 0
    cleaned_character_count: int = 0
    title_detected: bool = False
    abstract_detected: bool = False
    number_of_sections: int = 0
    reference_section_detected: bool = False
    duplicate_text_warnings: List[str] = field(default_factory=list)
    possible_scanned_document: bool = False
    extraction_success: bool = False
    cleanup_warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    final_usability_status: str = "usable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdf_found": self.pdf_found,
            "page_count": self.page_count,
            "extracted_character_count": self.extracted_character_count,
            "cleaned_character_count": self.cleaned_character_count,
            "title_detected": self.title_detected,
            "abstract_detected": self.abstract_detected,
            "number_of_sections": self.number_of_sections,
            "reference_section_detected": self.reference_section_detected,
            "duplicate_text_warnings": self.duplicate_text_warnings,
            "possible_scanned_document": self.possible_scanned_document,
            "extraction_success": self.extraction_success,
            "cleanup_warnings": self.cleanup_warnings,
            "errors": self.errors,
            "final_usability_status": self.final_usability_status,
        }
