from __future__ import annotations

from typing import Any

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult


class PmcProvider:
    name = "pmc"
    supported_identifiers = {"pmcid"}

    def can_handle(self, item: dict[str, Any]) -> bool:
        return bool(str(item.get("pmcid") or item.get("PMCID") or "").strip())

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        return MetadataResult("not_implemented", self.name, dict(item))

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        return FulltextResult("structured_fulltext_unavailable", self.name, errors=["PMC XML retrieval is not implemented yet."])

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        return MarkdownResult("failed", source_quality="unavailable", errors=["PMC Markdown generation is not implemented yet."])
