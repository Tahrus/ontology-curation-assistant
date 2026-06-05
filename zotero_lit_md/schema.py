from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


ExtractionStatus = Literal["complete", "partial", "failed", "warning"]
ChunkType = Literal[
    "abstract",
    "introduction",
    "method",
    "result",
    "discussion",
    "conclusion",
    "reference",
    "table",
    "figure_caption",
    "declaration",
    "other",
]


@dataclass
class PaperMetadata:
    title: str = ""
    doi: str = ""
    citation: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages_or_article_number: str = ""
    zotero_item_key: str = ""
    zotero_attachment_key: str = ""
    zotero_collection: str = ""
    pdf_filename: str = ""
    pdf_path: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    lead_author: str = ""


@dataclass
class ExtractionDiagnostics:
    pdf_pages: int = 0
    extracted_characters: int = 0
    text_extraction_method: str = "unknown"
    detected_layout: str = "unknown"
    tables_extracted: str = "no"
    equations_extracted: str = "partial"
    references_extracted: str = "no"
    extraction_status: ExtractionStatus = "failed"
    warnings: list[str] = field(default_factory=list)


@dataclass
class PageText:
    page_number: int
    text: str


@dataclass
class SectionBlock:
    heading: str
    level: int = 2
    page_start: int | None = None
    page_end: int | None = None
    text: str = ""
    subsections: list["SectionBlock"] = field(default_factory=list)


@dataclass
class RetrievalChunk:
    chunk_id: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    approx_tokens: int
    chunk_type: ChunkType
    key_terms: list[str]
    text: str


@dataclass
class ClaimUnit:
    claim_id: str
    claim: str
    evidence_section: str
    pages: str
    type: str


@dataclass
class ExtractedPaper:
    metadata: PaperMetadata
    diagnostics: ExtractionDiagnostics
    pages: list[PageText] = field(default_factory=list)
    sections: list[SectionBlock] = field(default_factory=list)
    retrieval_chunks: list[RetrievalChunk] = field(default_factory=list)
    claim_units: list[ClaimUnit] = field(default_factory=list)
    source_pdf: Path | None = None

    def sidecar_payload(self) -> dict[str, Any]:
        return {
            "metadata": asdict(self.metadata),
            "extraction_diagnostics": asdict(self.diagnostics),
            "sections": [asdict(section) for section in self.sections],
            "retrieval_chunks": [asdict(chunk) for chunk in self.retrieval_chunks],
            "claim_units": [asdict(claim) for claim in self.claim_units],
        }
