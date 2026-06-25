from __future__ import annotations

from typing import Any

import httpx

from backend.app.literature.providers.base import FulltextResult, MarkdownResult, MetadataResult
from backend.app.literature.publisher_xml import (
    ArticleApiRetrievalFailed,
    ElsevierApiConfig,
    collect_article_identifiers,
    parse_elsevier_xml,
    retrieve_article_via_api_with_identifier_fallback,
)


class ElsevierProvider:
    """Provider adapter around the existing Elsevier Article Retrieval implementation."""

    name = "elsevier"
    supported_identifiers = {"doi", "pii"}

    def __init__(self, config: ElsevierApiConfig, *, http_client: httpx.Client | None = None) -> None:
        self.config = config
        self.http_client = http_client

    def can_handle(self, item: dict[str, Any]) -> bool:
        return any(identifier.kind in self.supported_identifiers for identifier in collect_article_identifiers(item))

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult:
        return MetadataResult("not_attempted", self.name, dict(item))

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult:
        try:
            result = retrieve_article_via_api_with_identifier_fallback(item, self.config, http_client=self.http_client)
        except ArticleApiRetrievalFailed as exc:
            return FulltextResult(
                "failed",
                self.name,
                errors=[str(exc)],
                metadata={"identifier_attempts": exc.attempts},
            )
        return FulltextResult(
            "success",
            self.name,
            format="elsevier_xml",
            text=result.retrieval.xml_text,
            metadata={
                "retrieval": result.retrieval,
                "article": result.article,
                "used_identifier": result.used_identifier,
                "identifier_attempts": result.identifier_attempts,
                "api_retrieval_source": result.api_retrieval_source,
            },
        )

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult:
        article = fulltext.metadata.get("article")
        if article is not None:
            return MarkdownResult("success", article.markdown, "structured_xml")
        if not fulltext.text:
            return MarkdownResult("failed", source_quality="unavailable", errors=["No Elsevier XML text was available."])
        article = parse_elsevier_xml(fulltext.text)
        if not article.has_full_text:
            return MarkdownResult("failed", source_quality="unavailable", errors=["Elsevier XML did not contain structured full text."])
        return MarkdownResult("success", article.markdown, "structured_xml")
