from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from urllib.parse import quote, unquote
from xml.etree import ElementTree as ET

import httpx


LOGGER = logging.getLogger(__name__)
IDENTIFIER_ORDER = ("pii", "doi", "pmid", "pmcid", "arxiv", "isbn", "issn", "url")
ELSEVIER_SUPPORTED_IDENTIFIERS = {"pii", "doi"}


@dataclass(frozen=True)
class ElsevierApiConfig:
    api_key: str | None
    inst_token: str | None = None
    base_url: str = "https://api.elsevier.com"
    enabled: bool = False


@dataclass(frozen=True)
class ArticleIdentifier:
    kind: str
    value: str
    source: str = "zotero"


@dataclass(frozen=True)
class LiteratureIdentification:
    zotero_key: str | None = None
    doi: str | None = None
    pii: str | None = None
    sciencedirect_url: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: str | None = None
    journal: str | None = None
    item_type: str | None = None
    pdf_path: str | None = None
    metadata_source: str = "manual"
    identifier_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ElsevierRetrieval:
    status: str
    xml_text: str | None
    lookup_type: str | None
    lookup_value: str | None
    status_code: int | None = None
    content_type: str | None = None
    request_url: str | None = None


@dataclass(frozen=True)
class StructuredArticle:
    title: str
    authors: list[str]
    journal: str | None
    year: str | None
    publication_date: str | None
    doi: str | None
    pii: str | None
    abstract: str | None
    markdown: str
    has_full_text: bool
    section_count: int = 0
    reference_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CrossrefMetadata:
    status: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    journal: str | None = None
    year: str | None = None
    doi: str | None = None


@dataclass(frozen=True)
class ArticleApiRetrievalResult:
    retrieval: ElsevierRetrieval
    article: StructuredArticle
    used_identifier: ArticleIdentifier
    identifier_attempts: list[dict[str, str | None]]
    api_retrieval_source: str = "elsevier_article_retrieval_api"


class ArticleApiRetrievalFailed(RuntimeError):
    def __init__(self, message: str, attempts: list[dict[str, str | None]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class MissingApiConfigurationError(ArticleApiRetrievalFailed):
    pass


class ApiAuthenticationError(ArticleApiRetrievalFailed):
    pass


class ApiPermissionError(ArticleApiRetrievalFailed):
    pass


class ApiQuotaExceededError(ArticleApiRetrievalFailed):
    pass


class ElsevierArticleClient:
    def __init__(self, config: ElsevierApiConfig, *, http_client: httpx.Client | None = None) -> None:
        self.config = config
        self.http_client = http_client or httpx.Client(timeout=30.0)

    def retrieve(self, *, doi: str | None = None, pii: str | None = None, sciencedirect_url: str | None = None) -> ElsevierRetrieval:
        lookup_type, lookup_value = elsevier_lookup_identifier(doi=doi, pii=pii, sciencedirect_url=sciencedirect_url)
        if not lookup_type or not lookup_value:
            return ElsevierRetrieval("not_eligible", None, None, None)
        if not self.config.enabled:
            return ElsevierRetrieval("disabled", None, lookup_type, lookup_value)
        if not self.config.api_key:
            return ElsevierRetrieval("not_configured", None, lookup_type, lookup_value)
        base_url = self.config.base_url.rstrip("/")
        article_url = base_url if base_url.endswith("/content/article") else f"{base_url}/content/article"
        url = f"{article_url}/{lookup_type}/{quote(lookup_value, safe='')}"
        headers = {"Accept": "text/xml", "X-ELS-APIKey": self.config.api_key}
        if self.config.inst_token:
            headers["X-ELS-Insttoken"] = self.config.inst_token
        try:
            response = self.http_client.get(url, headers=headers)
        except httpx.RequestError:
            return ElsevierRetrieval("request_failed", None, lookup_type, lookup_value, request_url=url)
        if response.status_code != 200:
            return ElsevierRetrieval(f"http_{response.status_code}", None, lookup_type, lookup_value, response.status_code, response.headers.get("Content-Type"), url)
        text = response.text.strip()
        if not text or "<" not in text:
            return ElsevierRetrieval("invalid_xml", None, lookup_type, lookup_value, response.status_code, response.headers.get("Content-Type"), url)
        return ElsevierRetrieval("success", text, lookup_type, lookup_value, response.status_code, response.headers.get("Content-Type"), url)


def collect_article_identifiers(metadata: dict[str, object]) -> list[ArticleIdentifier]:
    """Collect normalized Zotero identifiers in deterministic publisher lookup order."""
    values: dict[str, list[tuple[object, str]]] = {kind: [] for kind in IDENTIFIER_ORDER}

    def add(kind: str, value: object, source: str = "zotero") -> None:
        if isinstance(value, (list, tuple, set)):
            for item in value:
                add(kind, item, source)
            return
        values[kind].append((value, source))

    for key in ("pii", "PII"):
        add("pii", metadata.get(key))
    doi_values = [metadata.get(key) for key in ("DOI", "doi")]
    url_values = [metadata.get(key) for key in ("url", "URL", "sciencedirect_url")]
    for candidate in [*doi_values, *url_values]:
        if match := re.search(r"\bS[0-9X][0-9X()\-\s]{10,}\b", str(candidate or ""), re.I):
            add("pii", match.group(), "zotero_embedded")
        if match := re.search(r"/pii/(S[0-9X()\-]+)", unquote(str(candidate or "")), re.I):
            add("pii", match.group(1), "zotero_url")
    for value in doi_values:
        add("doi", value)
    for key in ("ISSN", "issn"):
        add("issn", metadata.get(key))
    for key in ("ISBN", "isbn"):
        add("isbn", metadata.get(key))
    for value in url_values:
        add("url", value)
    for key in ("PMID", "pmid"):
        add("pmid", metadata.get(key))
    for key in ("PMCID", "pmcid"):
        add("pmcid", metadata.get(key))
    for key in ("arxiv", "arXiv", "arxiv_id", "arXiv ID"):
        add("arxiv", metadata.get(key))
    for candidate in url_values:
        if match := re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", str(candidate or ""), re.I):
            add("arxiv", match.group(1), "zotero_url")
    extra = str(metadata.get("extra") or "")
    if match := re.search(r"^\s*PMID\s*:\s*(\d+)\s*$", extra, re.I | re.M):
        add("pmid", match.group(1), "zotero_extra")
    if match := re.search(r"^\s*PMCID\s*:\s*(PMC\d+)\s*$", extra, re.I | re.M):
        add("pmcid", match.group(1), "zotero_extra")

    identifiers: list[ArticleIdentifier] = []
    seen: set[tuple[str, str]] = set()
    for kind in IDENTIFIER_ORDER:
        for raw_value, source in values[kind]:
            normalized = _normalize_article_identifier(kind, raw_value)
            identity = (kind, normalized.casefold())
            if not normalized or identity in seen:
                continue
            seen.add(identity)
            identifiers.append(ArticleIdentifier(kind, normalized, source))
    return identifiers


def retrieve_article_via_api_with_identifier_fallback(
    metadata: dict[str, object],
    api_config: ElsevierApiConfig,
    *,
    http_client: httpx.Client | None = None,
) -> ArticleApiRetrievalResult:
    """Try supported identifiers without weakening configuration/authentication failures."""
    identifiers = collect_article_identifiers(metadata)
    attempts: list[dict[str, str | None]] = []
    if not api_config.enabled:
        raise MissingApiConfigurationError("Elsevier publisher API is disabled. Enable it under Settings > Publisher API.")
    if not api_config.api_key:
        raise MissingApiConfigurationError("Elsevier API key is missing. Configure it under Settings > Publisher API.")
    if not identifiers:
        raise ArticleApiRetrievalFailed("No supported article identifiers were found. Human metadata fix required.")

    client = ElsevierArticleClient(api_config, http_client=http_client)
    for identifier in identifiers:
        if identifier.kind not in ELSEVIER_SUPPORTED_IDENTIFIERS:
            reason = "not supported by Elsevier Article Retrieval API"
            LOGGER.info("Skipping %s: %s", identifier.kind.upper(), reason)
            attempts.append({"kind": identifier.kind, "value": identifier.value, "status": "skipped", "reason": reason})
            continue
        LOGGER.info("Trying Elsevier API retrieval with %s: %s", identifier.kind.upper(), identifier.value)
        kwargs = {identifier.kind: identifier.value}
        retrieval = client.retrieve(**kwargs)
        attempt = {"kind": identifier.kind, "value": identifier.value, "status": retrieval.status, "reason": None}
        attempts.append(attempt)
        if retrieval.status == "http_401":
            raise ApiAuthenticationError("Elsevier API request failed with status 401. Check API key.", attempts)
        if retrieval.status == "http_403":
            raise ApiPermissionError("Elsevier API request failed with status 403. Check institutional access or entitlement.", attempts)
        if retrieval.status == "http_429":
            raise ApiQuotaExceededError("Elsevier API request failed with status 429. Check API quota or rate limits.", attempts)
        if retrieval.xml_text:
            try:
                article = parse_elsevier_xml(retrieval.xml_text)
            except ValueError:
                attempt["status"] = "invalid_xml"
                attempt["reason"] = "response was not valid structured article XML"
            else:
                if article.has_full_text:
                    return ArticleApiRetrievalResult(retrieval, article, identifier, attempts)
                attempt["status"] = "full_text_unavailable"
                attempt["reason"] = "response did not contain a structured full-text body"
        if attempt["status"] in {"http_400", "http_404", "invalid_xml", "full_text_unavailable", "not_eligible"}:
            LOGGER.info("%s retrieval failed: %s; trying the next identifier", identifier.kind.upper(), attempt["status"])
            continue
        raise ArticleApiRetrievalFailed(
            f"Elsevier API retrieval stopped after {identifier.kind.upper()} failed ({attempt['status']}). Human correction required.",
            attempts,
        )
    raise ArticleApiRetrievalFailed("API retrieval failed for all available identifiers. Human metadata fix required.", attempts)


def _normalize_article_identifier(kind: str, value: object) -> str:
    text = str(value or "").strip()
    if kind == "pii":
        return _normalize_pii(text)
    if kind == "doi":
        return _normalize_doi(text)
    if kind == "pmid":
        return re.sub(r"^PMID\s*:\s*", "", text, flags=re.I).strip()
    if kind == "pmcid":
        normalized = re.sub(r"^PMCID\s*:\s*", "", text, flags=re.I).strip().upper()
        return normalized
    if kind == "arxiv":
        return re.sub(r"^(?:arxiv\s*:\s*)", "", text, flags=re.I).strip()
    return text


def retrieve_crossref_metadata(doi: str | None, *, http_client: httpx.Client | None = None) -> CrossrefMetadata:
    normalized = _normalize_doi(doi)
    if not normalized:
        return CrossrefMetadata("not_eligible")
    client = http_client or httpx.Client(timeout=15.0)
    try:
        response = client.get(f"https://api.crossref.org/works/{quote(normalized, safe='')}", headers={"Accept": "application/json"})
    except httpx.RequestError:
        return CrossrefMetadata("request_failed")
    if response.status_code != 200:
        return CrossrefMetadata(f"http_{response.status_code}")
    try:
        message = response.json().get("message", {})
    except (ValueError, AttributeError):
        return CrossrefMetadata("invalid_response")
    if not isinstance(message, dict):
        return CrossrefMetadata("invalid_response")
    titles = message.get("title") or []
    containers = message.get("container-title") or []
    authors = []
    for author in message.get("author") or []:
        if isinstance(author, dict):
            name = " ".join(str(author.get(key) or "").strip() for key in ("given", "family")).strip()
            if name:
                authors.append(name)
    year = None
    for date_key in ("published-print", "published-online", "published", "issued"):
        date_value = message.get(date_key)
        if isinstance(date_value, dict) and date_value.get("date-parts"):
            try:
                year = str(date_value["date-parts"][0][0])
                break
            except (IndexError, TypeError):
                continue
    return CrossrefMetadata(
        "success",
        title=str(titles[0]).strip() if titles else None,
        authors=authors,
        journal=str(containers[0]).strip() if containers else None,
        year=year,
        doi=_normalize_doi(str(message.get("DOI") or normalized)),
    )


def elsevier_lookup_identifier(*, doi: str | None, pii: str | None, sciencedirect_url: str | None) -> tuple[str | None, str | None]:
    if pii and (normalized := _normalize_pii(pii)):
        return "pii", normalized
    if doi and (normalized := _normalize_doi(doi)):
        return "doi", normalized
    url = unquote(sciencedirect_url or "")
    if match := re.search(r"/pii/(S[0-9X-]+)", url, re.I):
        return "pii", _normalize_pii(match.group(1))
    if match := re.search(r"10\.\d{4,9}/[^?#\s]+", url, re.I):
        return "doi", _normalize_doi(match.group())
    return None, None


def parse_elsevier_xml(xml_text: str) -> StructuredArticle:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("Elsevier API response was not valid article XML.") from exc
    title = _first_text(root, "title") or "Untitled article"
    doi = _normalize_doi(_first_text(root, "doi")) or None
    pii = _normalize_pii(_first_text(root, "pii-unformatted", "pii")) or None
    journal = _first_text(root, "publicationName", "publication-name") or None
    publication_date = _first_text(root, "coverDate", "cover-date", "date") or None
    year_match = re.search(r"\b(?:19|20)\d{2}\b", publication_date or "")
    year = year_match.group() if year_match else None
    authors = _authors(root)
    abstract_node = _first_element(root, "description", "abstract")
    abstract = _node_text(abstract_node) if abstract_node is not None else None
    blocks = [f"# {title}", ""]
    if abstract:
        blocks.extend(["## Abstract", "", abstract, ""])

    body = _first_element(root, "body")
    content_root = body if body is not None else root
    body_sections = _top_level_sections(content_root)
    body_paragraphs = _paragraphs_owned_by(content_root, owner=None) if body is not None else []
    if body_paragraphs:
        blocks.extend(["## Article Body", "", *body_paragraphs, ""])
    for section in body_sections:
        blocks.extend(_render_section(section, level=2))

    rendered_appendices = False
    appendices = _all_elements(root, "appendix")
    for index, appendix in enumerate(appendices, start=1):
        appendix_blocks = _render_appendix(appendix, index)
        if appendix_blocks:
            rendered_appendices = True
            blocks.extend(appendix_blocks)

    references = _references(root)
    if references:
        blocks.extend(["## References", ""])
        blocks.extend(f"{index}. {reference}" for index, reference in enumerate(references, start=1))
        blocks.append("")

    rendered_back_matter = _render_back_matter(root, blocks)
    warnings: list[str] = []
    appendix_like = bool(_all_elements(root, "appendices", "appendix"))
    if appendix_like and not rendered_appendices:
        warnings.append("Appendix-like XML content was detected but could not be parsed cleanly.")
    supplementary_like = bool(_all_elements(root, "supplementary-material", "supplement", "further-reading", "biography"))
    if supplementary_like and not rendered_back_matter:
        warnings.append("Supplementary or back-matter XML content was detected but could not be parsed cleanly.")
    markdown = "\n".join(blocks).strip() + "\n"
    return StructuredArticle(
        title=title,
        authors=authors,
        journal=journal,
        year=year,
        publication_date=publication_date,
        doi=doi,
        pii=pii,
        abstract=abstract,
        markdown=markdown,
        has_full_text=bool(body_sections or body_paragraphs),
        section_count=len(_all_elements(content_root, "section", "sec")),
        reference_count=len(references),
        warnings=warnings,
    )


def _local_name(element: ET.Element) -> str:
    return str(element.tag).split("}")[-1].split(":")[-1]


def _all_elements(root: ET.Element | None, *names: str) -> list[ET.Element]:
    wanted = set(names)
    return [element for element in root.iter() if _local_name(element) in wanted] if root is not None else []


def _first_element(root: ET.Element | None, *names: str) -> ET.Element | None:
    return next(iter(_all_elements(root, *names)), None)


def _first_text(root: ET.Element | None, *names: str) -> str:
    element = _first_element(root, *names)
    return _node_text(element)


def _node_text(element: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", " ".join(element.itertext())).strip() if element is not None else ""


def _normalize_doi(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    return value.rstrip(".,; ")


def _normalize_pii(value: str | None) -> str:
    value = (value or "").strip().upper()
    return re.sub(r"[\s()\-]", "", value.removeprefix("PII:"))


def _authors(root: ET.Element) -> list[str]:
    creators = [_node_text(element) for element in _all_elements(root, "creator") if _node_text(element)]
    if creators:
        return list(dict.fromkeys(creators))
    values: list[str] = []
    for author in _all_elements(root, "author"):
        given = _first_text(author, "given-name", "givenName", "initials")
        surname = _first_text(author, "surname")
        name = " ".join(part for part in (given, surname) if part).strip() or _node_text(author)
        if name:
            values.append(name)
    return list(dict.fromkeys(values))


def _top_level_sections(container: ET.Element | None) -> list[ET.Element]:
    if container is None:
        return []
    sections: list[ET.Element] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            if _local_name(child) in {"section", "sec"}:
                sections.append(child)
            elif _local_name(child) in {"appendix", "appendices", "bibliography", "references", "ref-list"}:
                continue
            else:
                visit(child)

    visit(container)
    return sections


def _child_sections(section: ET.Element) -> list[ET.Element]:
    return _top_level_sections(section)


def _owned_elements(container: ET.Element, *names: str) -> list[ET.Element]:
    wanted = set(names)
    values: list[ET.Element] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            if child is not container and _local_name(child) in {"section", "sec"}:
                continue
            if _local_name(child) in wanted:
                values.append(child)
            else:
                visit(child)

    visit(container)
    return values


def _paragraphs_owned_by(container: ET.Element | None, *, owner: ET.Element | None) -> list[str]:
    if container is None:
        return []
    scope = owner if owner is not None else container
    return [text for paragraph in _owned_elements(scope, "para", "p") if (text := _node_text(paragraph))]


def _direct_heading(section: ET.Element) -> str:
    for child in section:
        if _local_name(child) in {"section-title", "title"}:
            return _node_text(child)
    return ""


def _render_section(section: ET.Element, *, level: int) -> list[str]:
    heading = _direct_heading(section) or "Section"
    blocks = [f"{'#' * min(level, 6)} {heading}", ""]
    for paragraph in _paragraphs_owned_by(section, owner=section):
        blocks.extend([paragraph, ""])
    for equation in _owned_elements(section, "formula", "math", "equation"):
        if text := _node_text(equation):
            blocks.extend([f"$$\n{text}\n$$", ""])
    for figure in _owned_elements(section, "figure", "fig"):
        caption = _first_text(figure, "caption") or _node_text(figure)
        if caption:
            blocks.extend([f"**Figure:** {caption}", ""])
    for table in _owned_elements(section, "table"):
        blocks.extend(_render_table(table))
    for child in _child_sections(section):
        blocks.extend(_render_section(child, level=level + 1))
    return blocks


def _render_table(table: ET.Element) -> list[str]:
    caption = _first_text(table, "caption")
    rows = []
    for row in _all_elements(table, "row", "tr"):
        cells = [_node_text(cell).replace("|", "\\|") for cell in _all_elements(row, "entry", "td", "th")]
        if cells:
            rows.append(cells)
    blocks = [f"**Table:** {caption or 'Table'}", ""]
    if rows:
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        blocks.extend(["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"])
        blocks.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        blocks.append("")
    elif text := _node_text(table):
        blocks.extend([text, ""])
    return blocks


def _render_appendix(appendix: ET.Element, index: int) -> list[str]:
    title = _first_text(appendix, "section-title", "title") or f"Appendix {chr(64 + index) if index <= 26 else index}"
    blocks = [f"## {title}", ""]
    paragraphs = _paragraphs_owned_by(appendix, owner=None)
    for paragraph in paragraphs:
        blocks.extend([paragraph, ""])
    for section in _top_level_sections(appendix):
        blocks.extend(_render_section(section, level=3))
    return blocks if len(blocks) > 2 else []


def _references(root: ET.Element) -> list[str]:
    bibliography = _first_element(root, "bibliography", "references", "ref-list")
    reference_root = bibliography if bibliography is not None else root
    references = [_node_text(element) for element in _all_elements(reference_root, "bib-reference", "reference", "ref")]
    return list(dict.fromkeys(reference for reference in references if reference))


def _render_back_matter(root: ET.Element, blocks: list[str]) -> bool:
    headings = {
        "acknowledgment": "Acknowledgments",
        "acknowledgements": "Acknowledgments",
        "supplementary-material": "Supplementary Material",
        "supplement": "Supplementary Material",
        "further-reading": "Further Reading",
        "biography": "Biography",
    }
    rendered = False
    seen: set[int] = set()
    for element in root.iter():
        name = _local_name(element)
        if name not in headings or id(element) in seen:
            continue
        seen.add(id(element))
        text = _node_text(element)
        if text:
            blocks.extend([f"## {headings[name]}", "", text, ""])
            rendered = True
    return rendered
