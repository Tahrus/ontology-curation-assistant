from __future__ import annotations

from typing import Any

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult


class ArxivProvider:
    name = "arxiv"
    supported_identifiers = {"arxiv", "url"}

    def can_handle(self, item: dict[str, Any]) -> bool:
        url = str(item.get("url") or item.get("URL") or "")
        return bool(item.get("arxiv") or item.get("arxiv_id") or "arxiv.org" in url)

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        return MetadataResult("not_implemented", self.name, dict(item))

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        return FulltextResult("structured_fulltext_unavailable", self.name, errors=["arXiv source/e-print retrieval is not implemented yet."])

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        return MarkdownResult("failed", source_quality="unavailable", errors=["arXiv LaTeX/source Markdown conversion is not implemented yet."])
