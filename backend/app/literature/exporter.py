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


def refresh_literature_markdown_repository(
    session: Session,
    repository_path: Path | None = None,
    *,
    structure: str = "sections",
    include_pages: bool = False,
) -> list[Path]:
    """Refresh the per-paper LLM-ready Markdown repository from stored literature."""
    payload = build_literature_payload(session, structure=structure, include_pages=include_pages)
    validate_literature_payload(payload)
    from backend.app.literature.repository import write_llm_ready_repository

    return write_llm_ready_repository(payload, repository_path)


def build_literature_payload(
    session: Session,
    *,
    structure: str = "sections",
    include_pages: bool = False,
) -> dict[str, Any]:
    if structure != "sections":
        raise ValueError("Only section-based literature export is currently supported")
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
            include_pages=include_pages,
        )
        keys = _dedupe_keys(paper)
        if keys & seen_keys:
            continue
        seen_keys.update(keys)
        papers.append(paper)

    for document in unlinked_documents:
        paper = _document_paper(document, include_pages=include_pages)
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
        raise ValueError("Unsupported literature payload schema version")
    papers = payload.get("papers")
    if not isinstance(papers, list):
        raise ValueError("Literature payload must contain a papers list")
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
        pdf_text = paper.get("pdf_text") or {}
        if pdf_text.get("structure") != "sections":
            raise ValueError(f"Paper {paper_id} must expose section-based pdf_text")
        if not isinstance(pdf_text.get("sections"), list):
            raise ValueError(f"Paper {paper_id} must contain pdf_text.sections")
        pages = pdf_text.get("pages") or []
        if any("text" in page for page in pages) and pdf_text.get("structure") == "sections":
            # Page text is allowed only for explicit debug/provenance exports.
            pass
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
    include_pages: bool,
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
    pdf_text = _pdf_text_payload(
        paper_id=paper_id,
        documents=documents,
        zotero_item_key=source.provider_item_key,
        include_pages=include_pages,
    )
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
        "pdf_text": pdf_text,
        "full_text": full_text,
        "chunks": _chunks_from_pdf_text(paper_id, pdf_text, sections, full_text),
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


def _document_paper(document: LiteratureDocument, *, include_pages: bool = False) -> dict[str, Any]:
    full_text = _normalize_text(document.content)
    sections = _section_map(full_text, None)
    paper_id = _paper_id(None, None, document.path)
    pdf_text = _pdf_text_payload(
        paper_id=paper_id,
        documents=[document],
        zotero_item_key=None,
        include_pages=include_pages,
    )
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
        "pdf_text": pdf_text,
        "full_text": full_text,
        "chunks": _chunks_from_pdf_text(paper_id, pdf_text, sections, full_text),
        "quality_flags": _quality_flags(document.filename, None, full_text, [document]),
        "source_metadata": {
            "created_at": document.created_at.isoformat(),
            "size_bytes": document.size_bytes,
        },
    }


def _combined_text(documents: list[LiteratureDocument]) -> str | None:
    parts = [_normalize_text(document.content) for document in documents if document.content]
    return "\n\n".join(part for part in parts if part) or None


def _pdf_text_payload(
    *,
    paper_id: str,
    documents: list[LiteratureDocument],
    zotero_item_key: str | None,
    include_pages: bool,
) -> dict[str, Any]:
    pages = _document_pages(documents)
    full_text = _normalize_text("\n\n".join(page["text"] for page in pages if page["text"]))
    sections = detect_structured_sections(pages)
    status = "success" if full_text else "missing_text"
    return {
        "source": "zotero_literature_storage" if zotero_item_key else "local_document",
        "zotero_item_key": zotero_item_key if is_valid_zotero_item_key(zotero_item_key) else None,
        "zotero_attachment_key": None,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": None if full_text else "No extracted text is available.",
        "structure": "sections",
        "sections": sections,
        "pages": _page_provenance(pages, include_text=include_pages),
    }


def _document_pages(documents: list[LiteratureDocument]) -> list[dict[str, Any]]:
    pages = []
    page_number = 1
    for document in documents:
        if not document.content:
            continue
        raw_pages = str(document.content).split("\f")
        for raw_page in raw_pages:
            text = _normalize_text(raw_page)
            if not text:
                page_number += 1
                continue
            pages.append({
                "page": page_number,
                "text": text,
                "source_file": document.path,
            })
            page_number += 1
    return pages


def _page_provenance(pages: list[dict[str, Any]], *, include_text: bool) -> list[dict[str, Any]]:
    if include_text:
        return [
            {
                "page": page["page"],
                "source_file": page["source_file"],
                "text": page["text"],
            }
            for page in pages
        ]
    return [
        {
            "page": page["page"],
            "source_file": page["source_file"],
            "char_count": len(page["text"]),
        }
        for page in pages
    ]


def detect_structured_sections(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = _page_lines(pages)
    heading_indices = [
        index
        for index, line in enumerate(lines)
        if _heading_candidate(line["text"], _next_nonblank(lines, index))
    ]
    sections: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    order_counters: dict[int, int] = {}
    current: dict[str, Any] | None = None

    if lines and (not heading_indices or heading_indices[0] > 0):
        first_heading_index = heading_indices[0] if heading_indices else len(lines)
        text = _join_line_text(lines[:first_heading_index])
        if text:
            current = _section_object(0, "Front matter", 0, lines[0]["page"])
            current["page_end"] = lines[max(first_heading_index - 1, 0)]["page"]
            current["text"] = text
            sections.append(current)
            stack = []

    for position, line_index in enumerate(heading_indices):
        line = lines[line_index]
        next_index = heading_indices[position + 1] if position + 1 < len(heading_indices) else len(lines)
        heading_info = _parse_heading(line["text"])
        if heading_info is None:
            heading_info = (line["text"].strip(), normalize_heading(line["text"]), 1)
        if heading_info is None:
            continue
        heading, normalized, level = heading_info
        order = _next_order(order_counters, level)
        section = _section_object(order, heading, level, line["page"])
        body_lines = lines[line_index + 1:next_index]
        if body_lines:
            section["page_end"] = body_lines[-1]["page"]
            section["text"] = _join_line_text(body_lines)

        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack and level > stack[-1]["level"]:
            stack[-1].setdefault("subsections", []).append(section)
        else:
            sections.append(section)
        stack.append(section)

    return sections


def _page_lines(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for page in pages:
        for line in page["text"].splitlines():
            text = line.strip()
            if text:
                result.append({"text": text, "page": page["page"]})
    return result


def _next_nonblank(lines: list[dict[str, Any]], index: int) -> str | None:
    for line in lines[index + 1:]:
        text = line["text"].strip()
        if text:
            return text
    return None


def _heading_candidate(text: str, next_text: str | None) -> bool:
    parsed = _parse_heading(text)
    if parsed is not None:
        return True
    if not next_text:
        return False
    stripped = text.strip()
    words = stripped.split()
    if len(stripped) > 90 or len(words) > 10:
        return False
    if stripped.endswith((".", ",", ";", ":")):
        return False
    if len(words) < 2:
        return False
    if len(next_text.split()) < 5:
        return False
    alpha = [char for char in stripped if char.isalpha()]
    if not alpha:
        return False
    title_like_words = [
        word for word in words
        if word[:1].isupper() or word.casefold() in {"and", "or", "of", "the", "in", "for"}
    ]
    title_like_ratio = len(title_like_words) / len(words)
    keyword_hint = any(
        keyword in normalize_heading(stripped)
        for keyword in [
            "framework",
            "monitoring",
            "processing",
            "solution",
            "method",
            "model",
            "data_acquisition",
        ]
    )
    return title_like_ratio >= 0.65 or (keyword_hint and len(next_text) >= 80)


def _parse_heading(text: str) -> tuple[str, str, int] | None:
    stripped = text.strip()
    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$", stripped)
    if numbered:
        number = numbered.group(1)
        heading = numbered.group(2).strip()
        if (
            len(heading) <= 120
            and len(heading.split()) <= 12
            and not re.search(r"\(\d{4}\)", heading)
            and not ("," in heading and number.count(".") == 0)
        ):
            return heading, normalize_heading(heading), number.count(".") + 1

    canonical = _canonical_heading(stripped)
    if canonical:
        return stripped, normalize_heading(stripped), 1
    return None


def _canonical_heading(text: str) -> str | None:
    normalized = normalize_heading(text)
    canonical = {
        "abstract",
        "summary",
        "introduction",
        "background",
        "methods",
        "methodology",
        "materials_and_methods",
        "experimental_procedures",
        "results",
        "findings",
        "discussion",
        "conclusion",
        "conclusions",
        "references",
        "bibliography",
    }
    return normalized if normalized in canonical else None


def normalize_heading(text: str) -> str:
    text = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s+", "", text.strip().casefold())
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _section_object(order: int | float, heading: str, level: int, page_start: int) -> dict[str, Any]:
    return {
        "order": order,
        "heading": heading,
        "heading_normalized": normalize_heading(heading),
        "level": level,
        "page_start": page_start,
        "page_end": page_start,
        "text": "",
        "subsections": [],
    }


def _next_order(order_counters: dict[int, int], level: int) -> int | float:
    order_counters[level] = order_counters.get(level, 0) + 1
    for deeper in list(order_counters):
        if deeper > level:
            order_counters.pop(deeper)
    if level <= 1:
        return order_counters[level]
    parent = order_counters.get(1, 0)
    child = order_counters[level]
    return float(f"{parent}.{child}")


def _join_line_text(lines: list[dict[str, Any]]) -> str:
    paragraphs = []
    current = []
    for line in lines:
        text = line["text"].strip()
        if not text:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(text)
    if current:
        paragraphs.append(" ".join(current))
    return _normalize_text("\n\n".join(paragraphs)) or ""


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


def _chunks_from_pdf_text(
    paper_id: str,
    pdf_text: dict[str, Any],
    sections: dict[str, str | None],
    full_text: str | None,
) -> list[dict[str, Any]]:
    structured_sections = _flatten_pdf_sections(pdf_text.get("sections") or [])
    chunks = []
    for section in structured_sections:
        text = section.get("text") or ""
        section_name = section.get("heading_normalized") or "section"
        for index, chunk_text in enumerate(_split_text(text, MAX_CHUNK_CHARS)):
            chunks.append({
                "chunk_id": f"{paper_id}:{section_name}:{index}",
                "paper_id": paper_id,
                "section": section_name,
                "chunk_index": index,
                "text": chunk_text,
                "page_start": section.get("page_start"),
                "page_end": section.get("page_end"),
            })
    return chunks or _chunks(paper_id, sections, full_text)


def _flatten_pdf_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = []
    for section in sections:
        flattened.append(section)
        flattened.extend(_flatten_pdf_sections(section.get("subsections") or []))
    return flattened


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
