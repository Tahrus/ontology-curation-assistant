from __future__ import annotations

from typing import Any

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult


class GenericHtmlProvider:
    name = "generic_html"
    supported_identifiers = {"url"}

    def can_handle(self, item: dict[str, Any]) -> bool:
        return bool(str(item.get("url") or item.get("URL") or "").startswith(("http://", "https://")))

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        return MetadataResult("not_implemented", self.name, dict(item))

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        return FulltextResult("structured_fulltext_unavailable", self.name, errors=["Generic structured HTML retrieval is not implemented yet."])

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        return MarkdownResult("failed", source_quality="unavailable", errors=["Generic HTML Markdown generation is not implemented yet."])
