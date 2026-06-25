from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class MetadataResult:
    status: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    links: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FulltextResult:
    status: str
    source: str
    format: str | None = None
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarkdownResult:
    status: str
    markdown: str | None = None
    source_quality: str = "unavailable"
    errors: list[str] = field(default_factory=list)


class LiteratureProvider(Protocol):
    name: str
    supported_identifiers: set[str]

    def can_handle(self, item: dict[str, Any]) -> bool: ...

    def resolve_metadata(self, item: dict[str, Any]) -> MetadataResult: ...

    def fetch_structured_fulltext(self, item: dict[str, Any]) -> FulltextResult: ...

    def generate_markdown(self, fulltext: FulltextResult) -> MarkdownResult: ...
