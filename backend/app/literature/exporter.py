from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models.db import AppSetting, LiteratureDocument, LiteratureSource


DEFAULT_LITERATURE_JSON = Path("literature") / "literature.json"
SCHEMA_VERSION = "1.0"
MAX_CHUNK_CHARS = 4000
ZOTERO_ITEM_KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{6,14}$")
SECTION_ALIASES = {
    "abstract": ["abstract", "summary"],
    "introduction": ["introduction", "background"],
    "methodology": ["methods", "methodology", "materials and methods", "experimental procedures"],
    "results": ["results", "findings"],
    "discussion": ["discussion"],
    "conclusion": ["conclusion", "conclusions"],
    "figures_tables": ["figure captions", "figures", "tables", "table captions"],
    "references": ["references", "bibliography"],
}


def export_literature_json(
    session: Session,
    output_path: Path = DEFAULT_LITERATURE_JSON,
) -> Path:
    """Write the authoritative LLM-ready literature library JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_literature_payload(session)
    validate_literature_payload(payload)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def build_literature_payload(session: Session) -> dict[str, Any]:
    sources = session.scalars(select(LiteratureSource).order_by(LiteratureSource.id)).all()
    documents = session.scalars(select(LiteratureDocument).order_by(LiteratureDocument.id)).all()
    library_type, library_id = _zotero_library_config(session)
    key_counts = Counter(source.provider_item_key for source in sources if source.provider_item_key)
    documents_by_source: dict[int, list[LiteratureDocument]] = {}
    unlinked_documents: list[LiteratureDocument] = []
    for document in documents:
        if document.source_id is None:
            unlinked_documents.append(document)
        else:
            documents_by_source.setdefault(document.source_id, []).append(document)

    papers = []
    seen_keys: set[str] = set()
    for source in sources:
        paper = _source_paper(
            source,
            documents_by_source.get(source.id, []),
            key_counts,
            library_type=library_type,
            library_id=library_id,
        )
        keys = _dedupe_keys(paper)
        if keys & seen_keys:
            continue
        seen_keys.update(keys)
        papers.append(paper)

    for document in unlinked_documents:
        paper = _document_paper(document)
        keys = _dedupe_keys(paper)
        if keys & seen_keys:
            continue
        seen_keys.update(keys)
        papers.append(paper)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Ontology Curation Assistant literature library",
        "papers": papers,
    }


def validate_literature_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported literature JSON schema version")
    papers = payload.get("papers")
    if not isinstance(papers, list):
        raise ValueError("Literature JSON must contain a papers list")
    seen_ids = set()
    for paper in papers:
        paper_id = paper.get("paper_id")
        if not paper_id or paper_id in seen_ids:
            raise ValueError("Each literature paper must have a unique paper_id")
        seen_ids.add(paper_id)
        zotero = paper.get("zotero") or {}
        item_key = zotero.get("item_key")
        uri = zotero.get("uri")
        if item_key and not is_valid_zotero_item_key(item_key):
            raise ValueError(f"Invalid Zotero item key for {paper_id}: {item_key}")
        if uri and item_key and item_key not in uri:
            raise ValueError(f"Zotero URI does not reference its item key for {paper_id}")
        if not any([paper.get("full_text"), paper.get("chunks"), (paper.get("sections") or {}).get("abstract")]):
            if "missing_full_text" not in paper.get("quality_flags", []):
                raise ValueError(f"Paper {paper_id} has no text and no missing_full_text flag")


def is_valid_zotero_item_key(value: str | None) -> bool:
    return bool(value and ZOTERO_ITEM_KEY_PATTERN.fullmatch(value))


def zotero_select_uri(
    item_key: str | None,
    *,
    library_type: str | None = None,
    library_id: str | None = None,
    duplicate: bool = False,
) -> tuple[str | None, list[str]]:
    diagnostics = []
    if not item_key:
        return None, ["missing_zotero_item_key"]
    if not is_valid_zotero_item_key(item_key):
        return None, ["malformed_zotero_item_key"]
    if duplicate:
        return None, ["duplicate_zotero_item_key"]
    if library_type == "group":
        if not library_id:
            return None, ["missing_zotero_group_id"]
        return f"zotero://select/groups/{library_id}/items/{item_key}", diagnostics
    return f"zotero://select/library/items/{item_key}", diagnostics


def _source_paper(
    source: LiteratureSource,
    documents: list[LiteratureDocument],
    key_counts: Counter[str],
    *,
    library_type: str | None,
    library_id: str | None,
) -> dict[str, Any]:
    creators = _json_list(source.creators_json)
    authors = [_creator_name(creator) for creator in creators if isinstance(creator, dict)]
    full_text = _combined_text(documents)
    sections = _section_map(full_text, source.abstract)
    uri, zotero_diagnostics = zotero_select_uri(
        source.provider_item_key,
        duplicate=bool(source.provider_item_key and key_counts[source.provider_item_key] > 1),
        library_type=library_type,
        library_id=library_id,
    )
    paper_id = _paper_id(source.provider_item_key, source.doi, documents[0].path if documents else source.title)
    paper = {
        "paper_id": paper_id,
        "zotero": {
            "item_key": source.provider_item_key if is_valid_zotero_item_key(source.provider_item_key) else None,
            "uri": uri,
            "library_id": library_id,
            "diagnostics": zotero_diagnostics,
        },
        "citation": {
            "title": source.title,
            "authors": authors,
            "year": _parse_year(source.year),
            "doi": source.doi,
            "journal": source.item_type,
        },
        "attachments": [_attachment_payload(document) for document in documents],
        "sections": sections,
        "full_text": full_text,
        "chunks": _chunks(paper_id, sections, full_text),
        "quality_flags": _quality_flags(source.title, source.abstract, full_text, documents),
        "source_metadata": {
            "provider": source.provider,
            "citation_key": source.citation_key,
            "zotero_version": source.zotero_version,
            "tags": _json_list(source.tags_json),
            "collections": _json_list(source.collections_json),
            "url": source.url,
            "synced_at": source.synced_at.isoformat() if source.synced_at else None,
        },
    }
    return paper


def _document_paper(document: LiteratureDocument) -> dict[str, Any]:
    full_text = _normalize_text(document.content)
    sections = _section_map(full_text, None)
    paper_id = _paper_id(None, None, document.path)
    return {
        "paper_id": paper_id,
        "zotero": {
            "item_key": None,
            "uri": None,
            "library_id": None,
            "diagnostics": ["missing_zotero_item_key"],
        },
        "citation": {
            "title": document.filename,
            "authors": [],
            "year": None,
            "doi": None,
            "journal": None,
        },
        "attachments": [_attachment_payload(document)],
        "sections": sections,
        "full_text": full_text,
        "chunks": _chunks(paper_id, sections, full_text),
        "quality_flags": _quality_flags(document.filename, None, full_text, [document]),
        "source_metadata": {
            "created_at": document.created_at.isoformat(),
            "size_bytes": document.size_bytes,
        },
    }


def _combined_text(documents: list[LiteratureDocument]) -> str | None:
    parts = [_normalize_text(document.content) for document in documents if document.content]
    return "\n\n".join(part for part in parts if part) or None


def _section_map(full_text: str | None, abstract: str | None) -> dict[str, str | None]:
    normalized_abstract = _normalize_text(abstract)
    sections = {name: None for name in SECTION_ALIASES}
    sections["abstract"] = normalized_abstract
    if not full_text:
        return sections

    detected = _detect_sections(full_text)
    for canonical, aliases in SECTION_ALIASES.items():
        if canonical == "abstract" and sections["abstract"]:
            continue
        for alias in aliases:
            if alias in detected:
                sections[canonical] = detected[alias]
                break

    if not any(value for value in sections.values()):
        sections["introduction"] = full_text
    return sections


def _detect_sections(text: str) -> dict[str, str]:
    heading_pattern = re.compile(
        r"(?im)^(?:\d+(?:\.\d+)*\s+)?"
        r"(abstract|summary|introduction|background|methods|methodology|materials and methods|"
        r"experimental procedures|results|findings|discussion|conclusion|conclusions|"
        r"figure captions|figures|tables|table captions|references|bibliography)\s*$"
    )
    matches = list(heading_pattern.finditer(text))
    detected = {}
    for index, match in enumerate(matches):
        heading = match.group(1).casefold()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _normalize_text(text[start:end])
        if body:
            detected[heading] = body
    return detected


def _chunks(paper_id: str, sections: dict[str, str | None], full_text: str | None) -> list[dict[str, Any]]:
    chunks = []
    section_items = [(name, text) for name, text in sections.items() if text]
    if not section_items and full_text:
        section_items = [("full_text", full_text)]
    for section, text in section_items:
        for index, chunk_text in enumerate(_split_text(text or "", MAX_CHUNK_CHARS)):
            chunks.append({
                "chunk_id": f"{paper_id}:{section}:{index}",
                "paper_id": paper_id,
                "section": section,
                "chunk_index": index,
                "text": chunk_text,
                "page_start": None,
                "page_end": None,
            })
    return chunks


def _split_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text else []
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(paragraph[i:i + max_chars] for i in range(0, len(paragraph), max_chars))
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _quality_flags(
    title: str | None,
    abstract: str | None,
    full_text: str | None,
    documents: list[LiteratureDocument],
) -> list[str]:
    flags = []
    if not title:
        flags.append("missing_title")
    if not documents:
        flags.append("missing_attachment")
    if not full_text:
        flags.append("missing_full_text")
    if not full_text and not abstract:
        flags.append("missing_text_content")
    for document in documents:
        if document.suffix == ".pdf" and not document.content:
            flags.append("possible_scanned_pdf")
    return sorted(set(flags))


def _attachment_payload(document: LiteratureDocument) -> dict[str, Any]:
    return {
        "type": document.suffix.lstrip(".") or "file",
        "filename": document.filename,
        "path": document.path,
        "available": Path(document.path).exists() if document.path else False,
        "mime_type": _mime_type(document.suffix),
        "text_extracted": bool(document.content),
    }


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text or None


def _creator_name(creator: dict[str, Any]) -> str:
    return " ".join(
        str(part).strip()
        for part in [creator.get("given"), creator.get("family")]
        if part is not None and str(part).strip()
    )


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _zotero_library_config(session: Session) -> tuple[str | None, str | None]:
    settings = get_settings()
    type_setting = session.get(AppSetting, "zotero_library_type")
    id_setting = session.get(AppSetting, "zotero_library_id")
    return (
        type_setting.value if type_setting is not None else settings.zotero_library_type,
        id_setting.value if id_setting is not None else settings.zotero_library_id,
    )


def _json_list(value: str | None) -> list[Any]:
    loaded = _json_loads(value, [])
    return loaded if isinstance(loaded, list) else []


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", str(value))
    return int(match.group(0)) if match else None


def _mime_type(suffix: str | None) -> str | None:
    return {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".tsv": "text/tab-separated-values",
        ".csv": "text/csv",
    }.get((suffix or "").lower())


def _paper_id(zotero_key: str | None, doi: str | None, fallback: str | None) -> str:
    if is_valid_zotero_item_key(zotero_key):
        return f"zotero-{zotero_key}"
    if doi:
        digest = hashlib.sha1(doi.casefold().encode("utf-8")).hexdigest()[:12]
        return f"doi-{digest}"
    digest = hashlib.sha1((fallback or "unknown").casefold().encode("utf-8")).hexdigest()[:12]
    return f"paper-{digest}"


def _dedupe_keys(paper: dict[str, Any]) -> set[str]:
    keys = {f"paper_id:{paper['paper_id']}"}
    zotero_key = paper.get("zotero", {}).get("item_key")
    doi = paper.get("citation", {}).get("doi")
    for attachment in paper.get("attachments", []):
        path = attachment.get("path")
        if path:
            keys.add(f"path:{str(path).casefold()}")
    if zotero_key:
        keys.add(f"zotero:{zotero_key.casefold()}")
    if doi:
        keys.add(f"doi:{str(doi).casefold()}")
    return keys
