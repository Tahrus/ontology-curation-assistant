import json
import re
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.db import LiteratureDocument, LiteratureSource


@dataclass(frozen=True)
class ParsedSource:
    title: str
    provider_item_key: str | None = None
    citation_key: str | None = None
    zotero_version: int | None = None
    item_type: str | None = None
    creators: list[dict[str, str | None]] = field(default_factory=list)
    year: str | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImportResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class LinkResult:
    linked: int = 0
    skipped: int = 0
    ambiguous: int = 0


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    normalized = re.sub(r"^https?://(dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.rstrip(".,;:)]}")
    return normalized or None


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    translator = str.maketrans({char: " " for char in string.punctuation})
    normalized = value.casefold().translate(translator)
    return " ".join(normalized.split())


def normalize_citation_key(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().casefold() or None


def load_zotero_metadata(path: Path) -> tuple[list[ParsedSource], int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed metadata JSON: {exc.msg}") from exc

    if not isinstance(payload, list):
        raise ValueError("Metadata file must contain a JSON list of Zotero items.")

    sources: list[ParsedSource] = []
    skipped = 0
    for item in payload:
        if not isinstance(item, dict):
            skipped += 1
            continue
        source = parse_source_item(item)
        if source is None:
            skipped += 1
            continue
        sources.append(source)
    return sources, skipped


def parse_source_item(item: dict) -> ParsedSource | None:
    data = item.get("data")
    if isinstance(data, dict):
        return _parse_zotero_api_item(item, data)
    return _parse_csl_item(item)


def _parse_csl_item(item: dict) -> ParsedSource | None:
    title = _clean_string(item.get("title"))
    if not title:
        return None

    return ParsedSource(
        provider_item_key=_clean_string(item.get("id") or item.get("key")),
        citation_key=_clean_string(item.get("citationKey")),
        title=title,
        item_type=_clean_string(item.get("type") or item.get("itemType")),
        creators=_parse_csl_creators(item.get("author") or item.get("creators") or []),
        year=_parse_issued_year(item.get("issued") or item.get("date")),
        doi=normalize_doi(_clean_string(item.get("DOI") or item.get("doi"))),
        url=_clean_string(item.get("URL") or item.get("url")),
        abstract=_clean_string(item.get("abstract") or item.get("abstractNote")),
        tags=_parse_string_list(item.get("tag") or item.get("tags")),
        collections=_parse_string_list(item.get("collection") or item.get("collections")),
    )


def _parse_zotero_api_item(item: dict, data: dict) -> ParsedSource | None:
    item_type = _clean_string(data.get("itemType"))
    if item_type in {"attachment", "note", "annotation"}:
        return None

    title = _clean_string(data.get("title"))
    if not title:
        return None

    return ParsedSource(
        provider_item_key=_clean_string(item.get("key") or data.get("key")),
        citation_key=_extract_citation_key(item, data),
        title=title,
        zotero_version=_parse_int(item.get("version") or data.get("version")),
        item_type=item_type,
        creators=_parse_zotero_creators(data.get("creators") or []),
        year=_parse_date_year(data.get("date")),
        doi=normalize_doi(_clean_string(data.get("DOI") or data.get("doi"))),
        url=_clean_string(data.get("url") or data.get("URL")),
        abstract=_clean_string(data.get("abstractNote") or data.get("abstract")),
        tags=_parse_zotero_tags(item.get("tags") or data.get("tags")),
        collections=_parse_string_list(item.get("collections") or data.get("collections")),
    )


def import_sources(session: Session, metadata_file: Path) -> ImportResult:
    sources, skipped = load_zotero_metadata(metadata_file)
    result = import_parsed_sources(session, sources, skipped=skipped, synced=False)
    return result


def import_parsed_sources(
    session: Session,
    sources: list[ParsedSource],
    *,
    skipped: int = 0,
    synced: bool = False,
) -> ImportResult:
    inserted = 0
    updated = 0

    for source in sources:
        existing = find_existing_source(session, source)
        if existing is None:
            session.add(source_to_record(source, synced=synced))
            inserted += 1
            continue

        update_source_record(existing, source, synced=synced)
        updated += 1

    session.commit()
    return ImportResult(inserted=inserted, updated=updated, skipped=skipped)


def find_existing_source(session: Session, source: ParsedSource) -> LiteratureSource | None:
    if source.provider_item_key:
        existing = session.scalar(
            select(LiteratureSource).where(
                LiteratureSource.provider == "zotero",
                LiteratureSource.provider_item_key == source.provider_item_key,
            )
        )
        if existing is not None:
            return existing

    if source.citation_key:
        existing = session.scalar(
            select(LiteratureSource).where(
                LiteratureSource.provider == "zotero",
                LiteratureSource.citation_key == source.citation_key,
            )
        )
        if existing is not None:
            return existing

    if source.doi:
        existing = session.scalar(
            select(LiteratureSource).where(LiteratureSource.normalized_doi == source.doi)
        )
        if existing is not None:
            return existing

    return session.scalar(
        select(LiteratureSource).where(
            LiteratureSource.provider == "zotero",
            LiteratureSource.normalized_title == normalize_title(source.title),
        )
    )


def source_to_record(source: ParsedSource, *, synced: bool = False) -> LiteratureSource:
    return LiteratureSource(
        provider="zotero",
        provider_item_key=source.provider_item_key,
        citation_key=source.citation_key,
        zotero_version=source.zotero_version,
        item_type=source.item_type,
        title=source.title,
        normalized_title=normalize_title(source.title),
        creators_json=json.dumps(source.creators),
        year=source.year,
        doi=source.doi,
        normalized_doi=source.doi,
        url=source.url,
        abstract=source.abstract,
        tags_json=json.dumps(source.tags),
        collections_json=json.dumps(source.collections),
        synced_at=datetime.now(timezone.utc) if synced else None,
    )


def update_source_record(
    record: LiteratureSource,
    source: ParsedSource,
    *,
    synced: bool = False,
) -> None:
    record.provider_item_key = source.provider_item_key or record.provider_item_key
    record.citation_key = source.citation_key or record.citation_key
    record.zotero_version = source.zotero_version
    record.item_type = source.item_type
    record.title = source.title
    record.normalized_title = normalize_title(source.title)
    record.creators_json = json.dumps(source.creators)
    record.year = source.year
    record.doi = source.doi
    record.normalized_doi = source.doi
    record.url = source.url
    record.abstract = source.abstract
    record.tags_json = json.dumps(source.tags)
    record.collections_json = json.dumps(source.collections)
    if synced:
        record.synced_at = datetime.now(timezone.utc)


def link_documents_to_sources(
    session: Session,
    literature_dir: Path,
    *,
    force: bool = False,
) -> LinkResult:
    root = literature_dir.resolve()
    documents = session.scalars(select(LiteratureDocument).order_by(LiteratureDocument.id)).all()
    sources = session.scalars(select(LiteratureSource).order_by(LiteratureSource.id)).all()

    linked = 0
    skipped = 0
    ambiguous = 0

    for document in documents:
        document_path = Path(document.path)
        try:
            document_path.resolve().relative_to(root)
        except ValueError:
            continue

        if document.source_id is not None and not force:
            skipped += 1
            continue

        matches = match_document_sources(document, sources)
        if len(matches) == 1:
            document.source_id = matches[0].id
            linked += 1
        elif len(matches) > 1:
            ambiguous += 1
        else:
            skipped += 1

    session.commit()
    return LinkResult(linked=linked, skipped=skipped, ambiguous=ambiguous)


def match_document_sources(
    document: LiteratureDocument,
    sources: list[LiteratureSource],
) -> list[LiteratureSource]:
    filename = Path(document.path).name.casefold()
    normalized_filename = normalize_title(filename)
    content = document.content or ""
    normalized_content = normalize_title(content)
    content_dois = extract_normalized_dois(content)

    matches: dict[int, LiteratureSource] = {}
    for source in sources:
        citation_key = normalize_citation_key(source.citation_key)
        if citation_key and citation_key in filename:
            matches[source.id] = source
            continue

        if source.normalized_doi and source.normalized_doi in content_dois:
            matches[source.id] = source
            continue

        source_title = source.normalized_title
        if source_title and (
            source_title in normalized_filename
            or source_title in normalized_content
        ):
            matches[source.id] = source

    return list(matches.values())


def extract_normalized_dois(text: str) -> set[str]:
    matches = re.findall(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[^\s,;]+)", text, re.I)
    return {
        normalized
        for match in matches
        if (normalized := normalize_doi(match))
    }


def _clean_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_csl_creators(value: object) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []
    creators = []
    for creator in value:
        if not isinstance(creator, dict):
            continue
        creators.append(
            {
                "family": _clean_string(creator.get("family")),
                "given": _clean_string(creator.get("given")),
                "type": _clean_string(creator.get("creatorType") or "author"),
            }
        )
    return creators


def _parse_zotero_creators(value: object) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []
    creators = []
    for creator in value:
        if not isinstance(creator, dict):
            continue
        creators.append(
            {
                "family": _clean_string(creator.get("lastName") or creator.get("family")),
                "given": _clean_string(creator.get("firstName") or creator.get("given")),
                "type": _clean_string(creator.get("creatorType") or "author"),
            }
        )
    return creators


def _parse_issued_year(value: object) -> str | None:
    if isinstance(value, dict):
        date_parts = value.get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list):
            return _clean_string(date_parts[0][0])
    return _parse_date_year(value)


def _parse_date_year(value: object) -> str | None:
    text = _clean_string(value)
    if text is None:
        return None
    match = re.search(r"\d{4}", text)
    return match.group(0) if match else None


def _parse_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = _clean_string(item)
        if text:
            result.append(text)
    return result


def _parse_zotero_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        if isinstance(item, dict):
            text = _clean_string(item.get("tag"))
        else:
            text = _clean_string(item)
        if text:
            tags.append(text)
    return tags


def _extract_citation_key(item: dict, data: dict) -> str | None:
    direct = _clean_string(data.get("citationKey") or item.get("citationKey"))
    if direct:
        return direct

    extra = _clean_string(data.get("extra"))
    if not extra:
        return None

    match = re.search(r"^\s*Citation Key:\s*(.+?)\s*$", extra, re.I | re.M)
    return _clean_string(match.group(1)) if match else None


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
