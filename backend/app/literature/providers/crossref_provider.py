from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult


class CrossrefProvider:
    name = "crossref"
    supported_identifiers = {"doi"}

    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        self.http_client = http_client or httpx.Client(timeout=15.0)

    def can_handle(self, item: dict[str, Any]) -> bool:
        return bool(str(item.get("doi") or item.get("DOI") or "").strip())

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        doi = str(item.get("doi") or item.get("DOI") or "").strip().removeprefix("doi:")
        if not doi:
            return MetadataResult("not_eligible", self.name)
        try:
            response = self.http_client.get(f"https://api.crossref.org/works/{quote(doi, safe='')}", headers={"Accept": "application/json"})
        except httpx.RequestError as exc:
            return MetadataResult("request_failed", self.name, errors=[str(exc)])
        if response.status_code != 200:
            return MetadataResult(f"http_{response.status_code}", self.name)
        try:
            message = response.json().get("message") or {}
        except (AttributeError, ValueError) as exc:
            return MetadataResult("invalid_response", self.name, errors=[str(exc)])
        authors = []
        for author in message.get("author") or []:
            if isinstance(author, dict):
                name = " ".join(str(author.get(key) or "").strip() for key in ("given", "family")).strip()
                if name:
                    authors.append(name)
        year = None
        for key in ("published-print", "published-online", "published", "issued"):
            date_parts = (message.get(key) or {}).get("date-parts") if isinstance(message.get(key), dict) else None
            if date_parts:
                year = str(date_parts[0][0])
                break
        metadata = {
            "title": ((message.get("title") or [None])[0]),
            "authors": authors,
            "year": year,
            "journal": ((message.get("container-title") or [None])[0]),
            "publisher": message.get("publisher"),
            "doi": message.get("DOI") or doi,
            "issn": message.get("ISSN") or message.get("issn"),
            "isbn": message.get("ISBN") or message.get("isbn"),
            "url": message.get("URL"),
        }
        links = [link for link in (message.get("link") or []) if isinstance(link, dict)]
        return MetadataResult("success", self.name, {key: value for key, value in metadata.items() if value not in (None, "", [])}, links)

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        metadata = self.resolve_metadata(item)
        if metadata.status != "success":
            return FulltextResult(metadata.status, self.name, metadata={"crossref": metadata.metadata}, errors=metadata.errors)
        structured_links = [link for link in metadata.links if "xml" in str(link.get("content-type") or link.get("content_type") or "").casefold()]
        pdf_links = [link for link in metadata.links if "pdf" in str(link.get("content-type") or link.get("content_type") or "").casefold()]
        if structured_links:
            return FulltextResult("structured_link_available", self.name, format="structured_link", metadata={"crossref": metadata.metadata, "links": structured_links})
        if pdf_links:
            return FulltextResult("pdf_available_but_not_used", self.name, format="pdf", metadata={"crossref": metadata.metadata, "links": pdf_links})
        return FulltextResult("structured_fulltext_unavailable", self.name, metadata={"crossref": metadata.metadata, "links": metadata.links})

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        return MarkdownResult("failed", source_quality="metadata_only", errors=["Crossref does not provide article body Markdown."])
