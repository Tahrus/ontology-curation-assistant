from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

import httpx


OLS_SEARCH_URL = "https://www.ebi.ac.uk/ols4/api/search"


@dataclass(frozen=True)
class OlsMatch:
    label: str
    ontology_id: str
    iri: str
    term_id: str | None
    description: str | None
    score: float
    should_map_existing: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def confidence_for_label(candidate_label: str, matched_label: str) -> float:
    candidate = " ".join(candidate_label.casefold().split())
    matched = " ".join(matched_label.casefold().split())
    if not candidate or not matched:
        return 0.0
    if candidate == matched:
        return 1.0
    if candidate in matched or matched in candidate:
        return 0.85
    return round(SequenceMatcher(None, candidate, matched).ratio(), 3)


def _first_description(doc: dict[str, Any]) -> str | None:
    description = doc.get("description")
    if isinstance(description, list) and description:
        return str(description[0])
    if isinstance(description, str) and description:
        return description
    return None


def parse_ols_search_response(candidate_label: str, payload: dict[str, Any]) -> list[OlsMatch]:
    docs = payload.get("response", {}).get("docs", [])
    matches: list[OlsMatch] = []

    for doc in docs:
        if not isinstance(doc, dict):
            continue

        label = str(doc.get("label") or "").strip()
        ontology_id = str(doc.get("ontology_name") or doc.get("ontology_prefix") or "").strip()
        iri = str(doc.get("iri") or "").strip()
        if not label or not ontology_id or not iri:
            continue

        score = confidence_for_label(candidate_label, label)
        matches.append(
            OlsMatch(
                label=label,
                ontology_id=ontology_id,
                iri=iri,
                term_id=str(doc.get("short_form") or "") or None,
                description=_first_description(doc),
                score=score,
                should_map_existing=score >= 0.82,
            )
        )

    return sorted(matches, key=lambda match: match.score, reverse=True)


class OlsLookupService:
    def __init__(
        self,
        *,
        base_url: str = OLS_SEARCH_URL,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.client = client

    def search(self, label: str, *, rows: int = 5) -> list[OlsMatch]:
        client = self.client or httpx.Client(timeout=self.timeout, follow_redirects=True)
        close_client = self.client is None
        try:
            response = client.get(
                self.base_url,
                params={"q": label, "rows": rows, "fieldList": "iri,label,ontology_name,short_form,description"},
            )
            response.raise_for_status()
            return parse_ols_search_response(label, response.json())
        finally:
            if close_client:
                client.close()
