from __future__ import annotations

from typing import Any

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult


class PdfProvider:
    name = "pdf"
    supported_identifiers = {"pdf_path"}

    def __init__(self, *, approved: bool = False) -> None:
        self.approved = approved

    def can_handle(self, item: dict[str, Any]) -> bool:
        return bool(self.approved and item.get("pdf_path"))

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        return MetadataResult("disabled" if not self.approved else "not_attempted", self.name, dict(item))

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        if not self.approved:
            return FulltextResult("pdf_available_but_not_used", self.name, format="pdf")
        return FulltextResult("pdf_fallback_requires_validation", self.name, format="pdf")

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        return MarkdownResult("failed", source_quality="unavailable", errors=["PDF extraction is disabled unless explicitly approved by the user."])
