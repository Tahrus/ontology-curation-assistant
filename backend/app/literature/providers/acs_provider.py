from __future__ import annotations

from typing import Any

import httpx

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult
from backend.app.literature.providers.crossref_provider import CrossrefProvider


class AcsProvider:
    name = "acs"
    supported_identifiers = {"doi"}

    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        self.crossref = CrossrefProvider(http_client=http_client)

    def can_handle(self, item: dict[str, Any]) -> bool:
        doi = str(item.get("doi") or item.get("DOI") or "").casefold()
        publisher = str(item.get("publisher") or "").casefold()
        return doi.startswith("10.1021/") or "american chemical society" in publisher

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        metadata = self.crossref.resolve_metadata(item)
        if metadata.status != "success":
            return metadata
        return MetadataResult(metadata.status, self.name, metadata.metadata, metadata.links, metadata.errors)

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        metadata = self.resolve_metadata(item)
        if metadata.status != "success":
            return FulltextResult(metadata.status, self.name, errors=metadata.errors)
        structured_links = [link for link in metadata.links if "xml" in str(link.get("content-type") or "").casefold()]
        pdf_links = [link for link in metadata.links if "pdf" in str(link.get("content-type") or "").casefold()]
        if structured_links:
            return FulltextResult("structured_link_available", self.name, format="tdm_xml", metadata={"crossref": metadata.metadata, "links": structured_links})
        if pdf_links:
            return FulltextResult("pdf_available_but_not_used", self.name, format="pdf", metadata={"crossref": metadata.metadata, "links": pdf_links})
        return FulltextResult("structured_fulltext_unavailable", self.name, metadata={"crossref": metadata.metadata, "links": metadata.links})

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        return MarkdownResult("failed", source_quality="metadata_only", errors=["No structured ACS full text was found."])
