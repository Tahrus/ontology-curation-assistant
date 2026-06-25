from __future__ import annotations

from typing import Any

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult


class PubmedProvider:
    name = "pubmed"
    supported_identifiers = {"pmid"}

    def can_handle(self, item: dict[str, Any]) -> bool:
        return bool(str(item.get("pmid") or item.get("PMID") or "").strip())

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        return MetadataResult("not_implemented", self.name, dict(item))

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        return FulltextResult("structured_fulltext_unavailable", self.name, errors=["PubMed metadata/PMCID discovery is not implemented yet."])

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        return MarkdownResult("failed", source_quality="metadata_only", errors=["PubMed does not provide article body Markdown."])
