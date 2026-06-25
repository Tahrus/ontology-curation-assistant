from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import unicodedata
from typing import Any
from urllib.parse import unquote

from backend.app.literature.publisher_xml import (
    ArticleApiRetrievalFailed,
    ElsevierApiConfig,
    LiteratureIdentification,
    collect_article_identifiers,
    parse_elsevier_xml,
    retrieve_article_via_api_with_identifier_fallback,
    retrieve_crossref_metadata,
)
from backend.app.literature.providers import AcsProvider, CrossrefProvider, ElsevierProvider

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.I)
PII_RE = re.compile(r"S\d{4}[\s-]?\d{4}\s*\(\d{2}\)\s*\d{5}[\s-]?\d|S\d{16}", re.I)
CURATION_FIELDS = {"project_tags", "review_status", "curation", "annotations", "ontology_suggestions", "include_in_llm_extraction", "document_role", "requires_manual_review", "state"}
MANAGED_ARTIFACT_DIRS = {
    "sources", "markdown", "metadata", "raw", "clean", "context", "reports",
    "papers", "blocked", "combined", "raw_markdown", "clean_markdown",
    "llm_context", "metadata_reports", "rejected_or_review_required",
    "Markdown", "Paper-PDF", "fallback", "api_tests",
}
EXTRACTION_MODES = {"publisher_api_required", "pdf_fallback_allowed", "pdf_only"}
DEFAULT_EXTRACTION_MODE = "publisher_api_required"


class LiteratureExtractionError(ValueError):
    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def _validate_extraction_mode(value: str) -> str:
    if value not in EXTRACTION_MODES:
        raise ValueError(f"Unsupported literature extraction mode: {value}")
    return value


def _failure_message(status: str, *, has_sciencedirect_url: bool = False) -> str:
    messages = {
        "not_configured": "Elsevier API key is missing. Configure it under Settings > Publisher API.",
        "disabled": "Publisher API extraction is disabled. Enable it under Settings > Publisher API.",
        "http_401": "Elsevier API request failed with status 401. Check the API key.",
        "http_403": "Elsevier API request failed with status 403. Check institutional access or entitlement.",
        "invalid_xml": "Elsevier API did not return valid XML/full-text content.",
        "full_text_unavailable": "Elsevier API did not return XML/full-text content.",
        "request_failed": "Elsevier API request failed because the service could not be reached.",
    }
    if status == "not_eligible":
        return "PII could not be extracted from Zotero metadata or the ScienceDirect URL." if has_sciencedirect_url else "No DOI, PII, or ScienceDirect URL found. Cannot use publisher API extraction."
    return messages.get(status, f"Elsevier API request failed ({status}).")


def _failure_diagnostics(mode: str, status: str, message: str, *, doi: str = "", pii: str = "", attempts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "extraction_mode": mode,
        "content_source": None,
        "metadata_source": None,
        "used_api_provider": "elsevier",
        "doi_used": doi or None,
        "pii_used": pii or None,
        "xml_retrieved": False,
        "pdf_used": False,
        "fallback_used": False,
        "extraction_status": "failed",
        "api_retrieval_status": status,
        "api_identifier_used_kind": None,
        "api_identifier_used_value": None,
        "api_identifier_attempts": attempts or [],
        "api_retrieval_source": "elsevier_article_retrieval_api",
        "extraction_errors": [message],
        "generated_artifacts": [],
    }


def _relative_artifact_path(paths: "RepositoryPaths", path: Path) -> str:
    return path.resolve().relative_to(paths.root.resolve()).as_posix()


def _artifact(path: str, artifact_type: str, ownership: str = "staged") -> dict[str, str]:
    return {"path": path, "artifact_type": artifact_type, "ownership": ownership}


def _deduplicate_artifacts(artifacts: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("path"):
            unique[f"{artifact['path']}::{artifact.get('artifact_type', '')}"] = artifact
    return list(unique.values())



def normalize_doi(value: str | None) -> str:
    value = unquote(value or "").strip().strip("`\"'").lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    return value.rstrip(".,; ")


def normalize_pii(value: str | None) -> str:
    value = (value or "").strip().strip("`\"'").upper()
    if value.startswith("PII:"):
        value = value[4:]
    return re.sub(r"[\s\-()]", "", value)


def normalize_title(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"\s+", " ", "".join(c if c.isalnum() or c.isspace() else " " for c in value)).strip()


def literature_identity_keys(metadata: dict[str, Any]) -> list[str]:
    keys: list[str] = []

    def add(kind: str, value: object) -> None:
        text = str(value or "").strip()
        if text:
            keys.append(f"{kind}:{text.casefold()}")

    add("doi", normalize_doi(str(metadata.get("doi") or metadata.get("DOI") or "")))
    add("pii", normalize_pii(str(metadata.get("pii") or metadata.get("PII") or "")))
    for key in ("pmid", "PMID"):
        add("pmid", metadata.get(key))
    for key in ("pmcid", "PMCID"):
        add("pmcid", metadata.get(key))
    for key in ("arxiv", "arXiv", "arxiv_id"):
        add("arxiv", metadata.get(key))
    for key in ("isbn", "ISBN"):
        value = metadata.get(key)
        if isinstance(value, list):
            for item in value:
                add("isbn", item)
        else:
            add("isbn", value)
    title = normalize_title(str(metadata.get("title") or ""))
    for key in ("issn", "ISSN"):
        value = metadata.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item and title:
                add("issn_title", f"{item}|{title}")
    add("url", metadata.get("url") or metadata.get("URL") or metadata.get("sciencedirect_url"))
    year = str(metadata.get("year") or "").strip()
    if title and year:
        add("title_year", f"{title}|{year}")
    return list(dict.fromkeys(keys))


def canonical_id(*, pii: str | None = None, doi: str | None = None, title: str | None = None) -> str:
    if value := normalize_pii(pii):
        return value
    if value := normalize_doi(doi):
        return re.sub(r"[^a-z0-9._-]+", "_", value).strip("_")
    return re.sub(r"\s+", "-", normalize_title(title)).strip("-")[:140] or "untitled-paper"


@dataclass(frozen=True)
class RepositoryPaths:
    root: Path
    sources: Path
    markdown: Path
    metadata: Path
    combined: Path
    archive: Path
    backups: Path
    curated: Path
    curated_markdown: Path
    curated_metadata: Path

    @classmethod
    def from_root(cls, root: Path) -> "RepositoryPaths":
        root = Path(root)
        curated = root / "curated"
        return cls(root, root / "sources", root / "markdown", root / "metadata", root / "combined_literature.md", root / "archive", root / "backups", curated, curated / "markdown", curated / "metadata")

    def ensure(self) -> None:
        for path in (self.root, self.sources, self.markdown, self.metadata, self.curated, self.curated_markdown, self.curated_metadata):
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class ImportResult:
    files_scanned: int = 0
    imported: int = 0
    duplicates: int = 0
    failed: int = 0
    combined_count: int = 0
    combined_output_file: str = ""
    failures: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["failures"] = self.failures or []
        return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def list_entries(paths: RepositoryPaths, *, ensure: bool = True) -> list[dict[str, Any]]:
    """List pipeline-generated staged entries without treating them as curated."""
    if ensure:
        paths.ensure()
    entries = []
    for path in sorted(paths.metadata.glob("*.json")) if paths.metadata.exists() else []:
        item = _read_json(path)
        if not item or item.get("archived") or not item.get("canonical_id"):
            continue
        markdown = Path(item["markdown_file"]) if item.get("markdown_file") else paths.markdown / f"{item.get('canonical_id', path.stem)}.md"
        item.setdefault("import_status", "staged")
        item.setdefault("curation_status", "needs_review")
        item.update(metadata_file=str(path), markdown_file=str(markdown) if markdown.exists() else None, markdown_available=markdown.exists(), repository_stage="staged")
        entries.append(item)
    return entries


def list_curated_entries(paths: RepositoryPaths, *, ensure: bool = True) -> list[dict[str, Any]]:
    if ensure:
        paths.ensure()
    entries: list[dict[str, Any]] = []
    for path in sorted(paths.curated_metadata.glob("*.json")):
        item = _read_json(path)
        if not item:
            continue
        markdown = paths.curated_markdown / f"{item.get('canonical_id', path.stem)}.md"
        item.update(metadata_file=str(path), markdown_file=str(markdown) if markdown.exists() else None, markdown_available=markdown.exists(), repository_stage="curated")
        entries.append(item)
    return entries


def extract_identifiers(text: str) -> tuple[str, str]:
    doi, pii = DOI_RE.search(text), PII_RE.search(text)
    return normalize_doi(doi.group()) if doi else "", normalize_pii(pii.group()) if pii else ""


def title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines()[:80]:
        line = re.sub(r"^#+\s*", "", line).strip()
        if not re.match(r"^(doi|pii|abstract|article|page)\b", line, re.I) and 4 <= len(line.split()) <= 35 and len(line) <= 240:
            return line
    return fallback.replace("_", " ").replace("-", " ").strip()


def clean_llm_markdown(body: str, *, title: str, pii: str = "", doi: str = "") -> str:
    body = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", body.strip(), flags=re.S)
    body = re.sub(r"\A#\s+.+?(?:\n+|$)", "", body)
    body = re.sub(r"(?im)^\s*(?:PII|DOI):\s*`?[^`\r\n]+`?\s*$\n?", "", body).strip()
    header = [f"# {title or 'Untitled article'}", ""]
    if pii:
        header.append(f"PII: `{normalize_pii(pii)}`")
    if doi:
        header.append(f"DOI: `{normalize_doi(doi)}`")
    if pii or doi:
        header.append("")
    return "\n".join(header) + "\n" + body + "\n"


def _existing(paths: RepositoryPaths, doi: str, pii: str, title: str) -> dict[str, Any] | None:
    entries = list_entries(paths)
    for item in entries:
        if (doi and normalize_doi(item.get("doi")) == doi) or (pii and normalize_pii(item.get("pii")) == pii):
            return item
    normalized = normalize_title(title)
    return next((item for item in entries if normalized and normalize_title(item.get("title")) == normalized), None)


def upsert_markdown(paths: RepositoryPaths, *, title: str, markdown: str, doi: str | None = None, pii: str | None = None, source_type: str = "local_markdown", source_path: Path | None = None, overwrite: bool = False, metadata_fields: dict[str, Any] | None = None, provenance: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    paths.ensure()
    found_doi, found_pii = extract_identifiers(markdown)
    doi, pii = normalize_doi(doi) or found_doi, normalize_pii(pii) or found_pii
    previous = _existing(paths, doi, pii, title)
    old_id = str((previous or {}).get("canonical_id") or "")
    target_id = canonical_id(pii=pii or (previous or {}).get("pii"), doi=doi or (previous or {}).get("doi"), title=title)
    now = datetime.now(timezone.utc).isoformat()
    metadata = {**(previous or {}), "canonical_id": target_id, "title": title or (previous or {}).get("title") or "Untitled article", "pii": pii or (previous or {}).get("pii") or None, "doi": doi or (previous or {}).get("doi") or None, "source_type": source_type, "source_path": str(source_path) if source_path else (previous or {}).get("source_path"), "import_status": "staged", "curation_status": "needs_review", "duplicate_status": "canonical_reused" if previous else "unique", "pipeline_version": "oca-canonical-v2", "imported_at": now, "updated_at": now}
    for key, value in (metadata_fields or {}).items():
        if value not in (None, "", []):
            metadata[key] = value
    metadata.setdefault("literature_type", _literature_type(str(metadata.get("item_type") or "")))
    metadata.update(provenance or {})
    metadata.setdefault("created_at", now)
    target = paths.markdown / f"{target_id}.md"
    old = paths.markdown / f"{old_id}.md" if old_id else None
    current = old.read_text(encoding="utf-8", errors="replace") if old and old.exists() else (target.read_text(encoding="utf-8", errors="replace") if target.exists() else "")
    candidate = clean_llm_markdown(markdown, title=metadata["title"], pii=metadata["pii"] or "", doi=metadata["doi"] or "")
    content_priority = {"raw_pdf_text": 0, "pdf_extraction": 1, "provided_markdown": 2, "elsevier_xml": 3}
    previous_content_source = str((previous or {}).get("content_source") or "")
    incoming_content_source = str((provenance or {}).get("content_source") or "")
    incoming_is_preferred = content_priority.get(incoming_content_source, 0) > content_priority.get(previous_content_source, 0)
    keep_preferred_existing = bool(previous and content_priority.get(previous_content_source, 0) > content_priority.get(incoming_content_source, 0))
    fallback_artifacts: list[dict[str, str]] = []
    fallback_text = current if incoming_is_preferred and previous_content_source == "pdf_extraction" else candidate if keep_preferred_existing and incoming_content_source == "pdf_extraction" else ""
    if fallback_text:
        fallback_path = paths.root / "fallback" / f"{target_id}.pdf.md"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        fallback_path.write_text(fallback_text, encoding="utf-8")
        metadata["pdf_fallback_markdown_path"] = _relative_artifact_path(paths, fallback_path)
        fallback_artifacts.append(_artifact(metadata["pdf_fallback_markdown_path"], "pdf_fallback_markdown"))
    if overwrite or not current or incoming_is_preferred or (not keep_preferred_existing and len(candidate.split()) > len(current.split())):
        target.write_text(candidate, encoding="utf-8")
    elif target != old:
        target.write_text(clean_llm_markdown(current, title=metadata["title"], pii=metadata["pii"] or "", doi=metadata["doi"] or ""), encoding="utf-8")
    if old_id and old_id != target_id:
        for obsolete in (paths.metadata / f"{old_id}.json", old):
            if obsolete and obsolete.exists() and obsolete != target:
                obsolete.unlink()
    for key in CURATION_FIELDS:
        if previous and key in previous:
            metadata[key] = previous[key]
    if keep_preferred_existing and previous:
        for key in ("title", "authors", "year", "journal", "doi", "pii", "abstract", "publication_date", "source_type", "source_path", "extraction_mode", "metadata_source", "content_source", "used_api_provider", "extraction_warnings", "api_retrieval_status", "lookup_doi", "lookup_pii", "doi_used", "pii_used", "xml_retrieved", "pdf_used", "fallback_used", "fallback_authorized_by", "extraction_status", "extraction_errors", "generated_artifacts", "xml_artifact_path", "xml_markdown_artifact_path"):
            if key in previous:
                metadata[key] = previous[key]
    metadata_path = paths.metadata / f"{target_id}.json"
    metadata["metadata_quality"] = metadata_quality(metadata)
    metadata["markdown_quality"] = markdown_quality(candidate, metadata)
    if not metadata["markdown_quality"]["ok"] and incoming_content_source != "manual_markdown":
        metadata["markdown_status"] = "manual_markdown_required"
        metadata["state"] = "curation_blocked"
        metadata["blocked_reason"] = "Structured Markdown quality checks failed. Please upload reviewed structured Markdown manually."
    metadata["artifacts"] = _deduplicate_artifacts([
        *(previous or {}).get("artifacts", []),
        *fallback_artifacts,
        _artifact(_relative_artifact_path(paths, target), "paper_markdown"),
        *([_artifact(_relative_artifact_path(paths, target), f"{incoming_content_source}_markdown")] if incoming_content_source and not keep_preferred_existing else []),
        _artifact(_relative_artifact_path(paths, metadata_path), "metadata_json"),
    ])
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata, previous is not None


def _unique_tags(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in (values or []) if value.strip()))


def _metadata_from_identification(identification: LiteratureIdentification, *, fallback_title: str | None = None) -> dict[str, Any]:
    literature_type = _literature_type(identification.item_type or str(identification.identifier_metadata.get("itemType") or ""))
    metadata = {
        "title": identification.title or fallback_title,
        "authors": identification.authors,
        "year": identification.year,
        "journal": identification.journal,
        "literature_type": literature_type,
        "item_type": identification.item_type,
        "doi": normalize_doi(identification.doi),
        "pii": normalize_pii(identification.pii),
        "url": identification.sciencedirect_url,
        "zotero_key": identification.zotero_key,
    }
    for key in (
        "pmid", "PMID", "pmcid", "PMCID", "arxiv", "arXiv", "arxiv_id", "isbn", "ISBN", "issn", "ISSN",
        "publisher", "abstract", "subtitle", "place", "edition", "volume", "series", "bookTitle",
        "book_title", "pages", "numPages", "language",
    ):
        if identification.identifier_metadata.get(key) not in (None, "", []):
            metadata[key.lower()] = identification.identifier_metadata[key]
    return {key: value for key, value in metadata.items() if value not in (None, "", [])}


def _literature_type(item_type: str | None) -> str:
    normalized = (item_type or "").strip().casefold()
    if normalized in {"book"}:
        return "book"
    if normalized in {"booksection", "book_section", "chapter"}:
        return "book_chapter"
    if normalized in {"editedbook", "edited_book"}:
        return "book"
    if normalized in {"conferencepaper", "conference_paper", "proceedings"}:
        return "conference_paper"
    if normalized in {"report"}:
        return "report"
    if normalized in {"preprint"}:
        return "preprint"
    return "journal_article"


def metadata_quality(entry: dict[str, Any]) -> dict[str, Any]:
    literature_type = entry.get("literature_type") or "journal_article"
    errors: list[str] = []
    warnings: list[str] = []
    if not entry.get("title"):
        errors.append("title is missing")
    authors = entry.get("authors") or []
    editors = entry.get("editors") or []
    if literature_type == "book" and not authors and not editors:
        errors.append("book author or editor is missing")
    elif literature_type != "book" and not authors:
        warnings.append("authors are missing")
    if not entry.get("year"):
        warnings.append("year is missing")
    if literature_type == "book":
        if not (entry.get("publisher") or entry.get("isbn")):
            warnings.append("book publisher or ISBN is missing")
    elif literature_type == "book_chapter":
        if not (entry.get("booktitle") or entry.get("book_title")):
            warnings.append("book chapter title/container is missing")
    elif not (entry.get("journal") or entry.get("publisher")):
        warnings.append("journal/source is missing")
    if not any(entry.get(key) for key in ("doi", "pii", "pmid", "pmcid", "arxiv", "arxiv_id", "isbn", "issn", "url")):
        warnings.append("stable identifier is missing")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def markdown_quality(markdown: str, entry: dict[str, Any]) -> dict[str, Any]:
    report = validate_markdown_candidate(markdown, entry)
    text = markdown.strip()
    warnings = list(report["warnings"])
    errors = list(report["errors"])
    literature_type = entry.get("literature_type") or "journal_article"
    if literature_type not in {"book", "book_chapter"} and "abstract" not in text.casefold():
        warnings.append("abstract is missing or not labelled")
    if len(re.findall(r"(?m)^#{2,3}\s+", text)) < 1:
        errors.append("no article/body sections were detected")
    if re.search(r"(?im)^#{1,3}\s+references\b", text) is None:
        warnings.append("references are not separated")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def create_metadata_only_entry(
    paths: RepositoryPaths,
    identification: LiteratureIdentification,
    *,
    extraction_mode: str,
    fulltext_status: str,
    message: str,
    attempted_providers: list[dict[str, Any]] | None = None,
    provider_errors: list[str] | None = None,
    http_client: Any = None,
    overwrite: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Create a staged metadata-only entry when structured full text is unavailable."""
    paths.ensure()
    metadata = _metadata_from_identification(identification)
    crossref_status = "not_attempted"
    crossref_links: list[dict[str, Any]] = []
    if metadata.get("doi"):
        crossref = CrossrefProvider(http_client=http_client).resolve_metadata(metadata)
        crossref_status = crossref.status
        crossref_links = crossref.links
        if crossref.status == "success":
            for key in ("title", "authors", "year", "journal", "publisher", "doi", "issn", "isbn", "url"):
                if not metadata.get(key) and crossref.metadata.get(key):
                    metadata[key] = crossref.metadata[key]
    metadata.setdefault("title", "Untitled literature item")
    metadata.setdefault("literature_type", _literature_type(str(metadata.get("item_type") or "")))
    metadata_quality_report = metadata_quality(metadata)

    provider_name = "acs" if AcsProvider(http_client=http_client).can_handle(metadata) else None
    if provider_name == "acs" and fulltext_status in {"failed", "not_configured", "disabled", "not_eligible", "structured_fulltext_unavailable"}:
        fulltext_status = "pdf_available_but_not_used" if any("pdf" in str(link.get("content-type") or "").casefold() for link in crossref_links) else "structured_fulltext_unavailable"
        message = "No structured ACS full text was found. A literature entry was created from metadata. Please upload structured Markdown manually, or explicitly approve PDF fallback."

    target_id = canonical_id(pii=str(metadata.get("pii") or ""), doi=str(metadata.get("doi") or ""), title=str(metadata.get("title") or ""))
    existing = _existing(paths, str(metadata.get("doi") or ""), str(metadata.get("pii") or ""), str(metadata.get("title") or ""))
    duplicate = existing is not None and not overwrite
    previous = existing or {}
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "metadata_source": "crossref" if crossref_status == "success" and identification.metadata_source == "manual" else f"{identification.metadata_source}+crossref" if crossref_status == "success" else identification.metadata_source,
        "attempted_providers": attempted_providers or [],
        "selected_provider": None,
        "fulltext_source": None,
        "fulltext_format": None,
        "fulltext_status": fulltext_status,
        "markdown_status": "manual_markdown_required",
        "source_quality": "metadata_only",
        "blocked_reason": message,
        "recommended_action": "Upload structured Markdown manually, or explicitly approve PDF fallback for this item.",
        "provider_errors": provider_errors or ([message] if message else []),
        "crossref_status": crossref_status,
        "crossref_links": crossref_links,
    }
    source_report_path = paths.metadata / f"{target_id}.source_report.json"
    metadata_path = paths.metadata / f"{target_id}.json"
    entry = {
        **previous,
        **metadata,
        "canonical_id": target_id,
        "source_type": "metadata_only",
        "import_status": "staged",
        "curation_status": "needs_manual_markdown",
        "duplicate_status": "canonical_reused" if previous else "unique",
        "pipeline_version": "oca-provider-v1",
        "extraction_mode": extraction_mode,
        "metadata_source": report["metadata_source"],
        "content_source": None,
        "used_api_provider": provider_name or "provider_registry",
        "fulltext_status": fulltext_status,
        "markdown_status": "manual_markdown_required",
        "source_quality": "metadata_only",
        "metadata_quality": metadata_quality_report,
        "state": "curation_blocked",
        "blocked_reason": message,
        "recommended_action": report["recommended_action"],
        "source_report_path": _relative_artifact_path(paths, source_report_path),
        "markdown_file": None,
        "markdown_available": False,
        "xml_retrieved": False,
        "pdf_used": False,
        "fallback_used": False,
        "fallback_authorized_by": None,
        "extraction_status": "manual_markdown_required",
        "extraction_errors": report["provider_errors"],
        "extraction_warnings": [message] if message else [],
        "api_retrieval_status": fulltext_status,
        "api_identifier_attempts": [attempt for provider in report["attempted_providers"] for attempt in provider.get("attempts", []) if isinstance(provider, dict)],
        "created_at": previous.get("created_at") or now,
        "imported_at": previous.get("imported_at") or now,
        "updated_at": now,
    }
    entry["artifacts"] = _deduplicate_artifacts([
        *(previous.get("artifacts") or []),
        _artifact(_relative_artifact_path(paths, metadata_path), "metadata_json"),
        _artifact(entry["source_report_path"], "source_report_json"),
    ])
    entry["generated_artifacts"] = [artifact["path"] for artifact in entry["artifacts"]]
    source_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry, duplicate


def validate_markdown_candidate(markdown: str, entry: dict[str, Any]) -> dict[str, Any]:
    text = markdown.strip()
    errors: list[str] = []
    warnings: list[str] = []
    if not re.search(r"(?m)^#\s+\S", text) and not entry.get("title"):
        errors.append("A title heading or metadata title is required.")
    if not (normalize_doi(entry.get("doi")) or normalize_pii(entry.get("pii")) or entry.get("pmid") or entry.get("pmcid") or entry.get("isbn") or entry.get("issn") or re.search(r"(?i)\b(doi|pii|pmid|pmcid|isbn|issn)\b", text)):
        errors.append("A stable identifier such as DOI, PII, PMID, PMCID, ISBN, or ISSN is required.")
    if not re.search(r"(?im)^#{1,3}\s+(source|provenance|metadata|abstract|introduction|methods?|results?|discussion|references?)\b", text):
        errors.append("Meaningful section headings or a provenance/source note are required.")
    words = re.findall(r"\b\w+\b", text)
    if len(words) < 40:
        errors.append("Markdown body is too short to curate safely.")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        short_line_ratio = sum(1 for line in lines if len(line) < 35 and not line.startswith("#")) / len(lines)
        if short_line_ratio > 0.65:
            errors.append("Body text appears to be mostly broken line fragments.")
        repeated_ratio = (len(lines) - len(set(lines))) / len(lines)
        if repeated_ratio > 0.25:
            warnings.append("Repeated lines may indicate headers or footers; review before curation.")
    if re.search(r"(?im)^#{1,3}\s+references\b", text) is None and re.search(r"(?i)\bdoi:\s*10\.\d{4,9}/", text):
        warnings.append("References may be present but are not separated under a References heading.")
    if re.search(r"(?i)\btable\b", text) and "|" not in text and "omitted" not in text.casefold():
        warnings.append("Tables are mentioned; ensure they are preserved or explicitly marked as omitted.")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def upload_manual_markdown(paths: RepositoryPaths, entry_id: str, *, markdown: str, validate: bool = True) -> dict[str, Any]:
    entry = _entry_by_id(list_entries(paths), entry_id, "Staged")
    paths.markdown.mkdir(parents=True, exist_ok=True)
    manual_path = paths.markdown / f"{entry_id}.manual.md"
    canonical_path = paths.markdown / f"{entry_id}.md"
    canonical_artifact_path = paths.markdown / f"{entry_id}.canonical.md"
    validation_path = paths.metadata / f"{entry_id}.validation_report.json"
    cleaned = clean_llm_markdown(markdown, title=entry.get("title") or "Untitled article", pii=entry.get("pii") or "", doi=entry.get("doi") or "")
    manual_path.write_text(cleaned, encoding="utf-8")
    validation = validate_markdown_candidate(cleaned, entry) if validate else {"ok": True, "errors": [], "warnings": []}
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entry["manual_markdown_path"] = _relative_artifact_path(paths, manual_path)
    entry["validation_report_path"] = _relative_artifact_path(paths, validation_path)
    entry["markdown_status"] = "manual_markdown_uploaded"
    entry["fulltext_status"] = "structured_fulltext_unavailable"
    entry["source_quality"] = "metadata_only"
    entry["validation_errors"] = validation["errors"]
    entry["validation_warnings"] = validation["warnings"]
    if validation["ok"]:
        canonical_path.write_text(cleaned, encoding="utf-8")
        canonical_artifact_path.write_text(cleaned, encoding="utf-8")
        entry["markdown_file"] = str(canonical_path)
        entry["canonical_markdown_path"] = _relative_artifact_path(paths, canonical_artifact_path)
        entry["markdown_available"] = True
        entry["markdown_status"] = "markdown_validated"
        entry["state"] = "ready_for_curation"
        entry["curation_status"] = "needs_review"
        entry["content_source"] = "manual_markdown"
        entry["source_quality"] = "manual_markdown"
        entry["blocked_reason"] = None
    else:
        entry["markdown_file"] = None
        entry["markdown_available"] = False
        entry["state"] = "curation_blocked"
        entry["curation_status"] = "needs_manual_markdown"
        entry["blocked_reason"] = "Manual Markdown validation failed. Fix the reported errors before curation."
    entry["artifacts"] = _deduplicate_artifacts([
        *entry.get("artifacts", []),
        _artifact(entry["manual_markdown_path"], "manual_markdown"),
        *([_artifact(entry["canonical_markdown_path"], "canonical_markdown")] if entry.get("canonical_markdown_path") else []),
        _artifact(entry["validation_report_path"], "validation_report_json"),
    ])
    entry["generated_artifacts"] = [artifact["path"] for artifact in entry["artifacts"]]
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    (paths.metadata / f"{entry_id}.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**entry, "validation_report": validation}


def _entry_by_id(entries: list[dict[str, Any]], entry_id: str, label: str) -> dict[str, Any]:
    entry = next((item for item in entries if item.get("canonical_id") == entry_id), None)
    if entry is None:
        raise FileNotFoundError(f"{label} literature entry not found: {entry_id}")
    return entry


def update_staged_entry(paths: RepositoryPaths, entry_id: str, *, metadata: dict[str, Any] | None = None, markdown: str | None = None, project_tags: list[str] | None = None) -> dict[str, Any]:
    entry = _entry_by_id(list_entries(paths), entry_id, "Staged")
    allowed = {"title", "authors", "year", "journal", "doi", "pii", "zotero_key", "notes"}
    for key, value in (metadata or {}).items():
        if key in allowed:
            entry[key] = value
    if project_tags is not None:
        entry["project_tags"] = _unique_tags(project_tags)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    entry["curation_status"] = "needs_review"
    metadata_path = paths.metadata / f"{entry_id}.json"
    metadata_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = paths.markdown / f"{entry_id}.md"
    if markdown is not None:
        markdown_path.write_text(clean_llm_markdown(markdown, title=entry.get("title") or "Untitled article", pii=entry.get("pii") or "", doi=entry.get("doi") or ""), encoding="utf-8")
    entry.update(metadata_file=str(metadata_path), markdown_file=str(markdown_path), markdown_available=markdown_path.exists(), repository_stage="staged")
    return entry


def promote_staged_entry(paths: RepositoryPaths, entry_id: str, *, metadata: dict[str, Any] | None = None, markdown: str | None = None, project_tags: list[str] | None = None) -> dict[str, Any]:
    staged = update_staged_entry(paths, entry_id, metadata=metadata, markdown=markdown, project_tags=project_tags)
    staged_markdown = Path(staged["markdown_file"]).read_text(encoding="utf-8", errors="replace")
    existing_path = paths.curated_metadata / f"{entry_id}.json"
    existing = _read_json(existing_path)
    now = datetime.now(timezone.utc).isoformat()
    curated = {
        **existing,
        **{key: staged.get(key) for key in ("canonical_id", "title", "authors", "year", "journal", "doi", "pii")},
        "project_tags": _unique_tags(project_tags if project_tags is not None else staged.get("project_tags")),
        "curation_status": "curated",
        "staged_entry_id": entry_id,
        "staged_metadata_file": str(paths.metadata / f"{entry_id}.json"),
        "source_type": staged.get("source_type"),
        "source_path": staged.get("source_path"),
        "zotero_key": staged.get("zotero_key"),
        "pipeline_version": staged.get("pipeline_version"),
        "metadata_source": staged.get("metadata_source"),
        "content_source": staged.get("content_source"),
        "extraction_mode": staged.get("extraction_mode"),
        "used_api_provider": staged.get("used_api_provider"),
        "doi_used": staged.get("doi_used"),
        "pii_used": staged.get("pii_used"),
        "xml_retrieved": staged.get("xml_retrieved"),
        "pdf_used": staged.get("pdf_used"),
        "fallback_used": staged.get("fallback_used"),
        "fallback_authorized_by": staged.get("fallback_authorized_by"),
        "extraction_status": staged.get("extraction_status"),
        "extraction_errors": staged.get("extraction_errors") or [],
        "generated_artifacts": staged.get("generated_artifacts") or [],
        "extraction_warnings": staged.get("extraction_warnings") or [],
        "api_retrieval_status": staged.get("api_retrieval_status"),
        "crossref_retrieval_status": staged.get("crossref_retrieval_status"),
        "lookup_doi": staged.get("lookup_doi"),
        "lookup_pii": staged.get("lookup_pii"),
        "xml_artifact_path": staged.get("xml_artifact_path"),
        "xml_markdown_artifact_path": staged.get("xml_markdown_artifact_path"),
        "pdf_fallback_markdown_path": staged.get("pdf_fallback_markdown_path"),
        "imported_at": staged.get("imported_at") or staged.get("created_at"),
        "curated_at": existing.get("curated_at") or now,
        "updated_at": now,
    }
    paths.curated_markdown.mkdir(parents=True, exist_ok=True)
    paths.curated_metadata.mkdir(parents=True, exist_ok=True)
    curated_markdown = paths.curated_markdown / f"{entry_id}.md"
    curated_markdown.write_text(staged_markdown, encoding="utf-8")
    curated["artifacts"] = _deduplicate_artifacts([
        _artifact(_relative_artifact_path(paths, curated_markdown), "paper_markdown", "curated"),
        _artifact(_relative_artifact_path(paths, existing_path), "metadata_json", "curated"),
    ])
    existing_path.write_text(json.dumps(curated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staged["import_status"] = "promoted"
    staged["promoted_literature_id"] = entry_id
    staged["promoted_at"] = now
    (paths.metadata / f"{entry_id}.json").write_text(json.dumps(staged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_combined(paths)
    curated.update(metadata_file=str(existing_path), markdown_file=str(curated_markdown), markdown_available=True, repository_stage="curated")
    return curated


def update_curated_entry(paths: RepositoryPaths, entry_id: str, *, metadata: dict[str, Any] | None = None, markdown: str | None = None, project_tags: list[str] | None = None) -> dict[str, Any]:
    entry = _entry_by_id(list_curated_entries(paths), entry_id, "Curated")
    allowed = {"title", "authors", "year", "journal", "doi", "pii", "notes", "curation_status"}
    for key, value in (metadata or {}).items():
        if key in allowed:
            entry[key] = value
    if project_tags is not None:
        entry["project_tags"] = _unique_tags(project_tags)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    metadata_path = paths.curated_metadata / f"{entry_id}.json"
    metadata_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = paths.curated_markdown / f"{entry_id}.md"
    if markdown is not None:
        markdown_path.write_text(clean_llm_markdown(markdown, title=entry.get("title") or "Untitled article", pii=entry.get("pii") or "", doi=entry.get("doi") or ""), encoding="utf-8")
    build_combined(paths)
    entry.update(metadata_file=str(metadata_path), markdown_file=str(markdown_path), markdown_available=markdown_path.exists(), repository_stage="curated")
    return entry


def reject_staged_entry(paths: RepositoryPaths, entry_id: str, *, delete: bool = False) -> dict[str, Any]:
    entry = _entry_by_id(list_entries(paths), entry_id, "Staged")
    if delete:
        for path in (paths.metadata / f"{entry_id}.json", paths.markdown / f"{entry_id}.md"):
            if path.exists():
                path.unlink()
        for source in paths.sources.glob(f"{entry_id}.*"):
            if source.is_file():
                source.unlink()
        return {"id": entry_id, "status": "deleted"}
    entry["import_status"] = "rejected"
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    (paths.metadata / f"{entry_id}.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"id": entry_id, "status": "rejected"}


def cleanup_unpromoted_staged(paths: RepositoryPaths, *, dry_run: bool = False) -> dict[str, Any]:
    """Delete uncurated and orphan generated artifacts inside the managed repository only."""
    root = paths.root.resolve()
    staged_entries = list_entries(paths, ensure=False)
    curated_entries = list_curated_entries(paths, ensure=False)
    promoted = [entry for entry in staged_entries if entry.get("promoted_literature_id")]
    unpromoted = [entry for entry in staged_entries if not entry.get("promoted_literature_id")]
    protected: set[str] = set()
    external_count = 0
    missing_count = 0
    errors: list[dict[str, str]] = []

    for entry in [*promoted, *curated_entries]:
        for artifact in entry.get("artifacts", []):
            if artifact.get("ownership") == "external":
                external_count += 1
            elif artifact.get("path"):
                protected.add(str(artifact["path"]).replace("\\", "/"))
        for key in ("metadata_file", "markdown_file"):
            if entry.get(key):
                try:
                    protected.add(Path(entry[key]).resolve().relative_to(root).as_posix())
                except ValueError:
                    external_count += 1

    candidates: set[Path] = set()
    staged_ids: list[str] = []
    for entry in unpromoted:
        staged_ids.append(str(entry["canonical_id"]))
        registered = entry.get("artifacts", [])
        for artifact in registered:
            if artifact.get("ownership") == "external":
                external_count += 1
                continue
            relative = str(artifact.get("path") or "").replace("\\", "/")
            if not relative:
                continue
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                external_count += 1
                continue
            candidates.add(candidate)
        entry_id = str(entry["canonical_id"])
        candidates.update({(paths.metadata / f"{entry_id}.json").resolve(), (paths.markdown / f"{entry_id}.md").resolve()})
        candidates.update(source.resolve() for source in paths.sources.glob(f"{entry_id}.*") if source.is_file())

    orphan_count = 0
    for folder_name in MANAGED_ARTIFACT_DIRS:
        folder = (root / folder_name).resolve()
        if not folder.exists() or not folder.is_dir():
            continue
        for candidate in folder.rglob("*"):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            relative = candidate.resolve().relative_to(root).as_posix()
            if relative in protected:
                continue
            if candidate.resolve() not in candidates:
                orphan_count += 1
            candidates.add(candidate.resolve())

    combined_removed = False
    if paths.combined.exists() and not curated_entries:
        candidates.add(paths.combined.resolve())
        combined_removed = True

    deleted_files: list[str] = []
    skipped_curated = 0
    for candidate in sorted(candidates, key=lambda value: str(value).casefold()):
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            external_count += 1
            continue
        if relative in protected:
            skipped_curated += 1
            continue
        if not candidate.exists():
            missing_count += 1
            continue
        if dry_run:
            deleted_files.append(relative)
            continue
        try:
            candidate.unlink()
            deleted_files.append(relative)
        except OSError as exc:
            errors.append({"path": relative, "error": str(exc)})

    directories_cleaned: list[str] = []
    if not dry_run:
        for folder_name in sorted(MANAGED_ARTIFACT_DIRS, key=len, reverse=True):
            folder = root / folder_name
            if not folder.exists() or not folder.is_dir():
                continue
            for directory in sorted((item for item in folder.rglob("*") if item.is_dir()), key=lambda value: len(value.parts), reverse=True):
                try:
                    directory.rmdir()
                    directories_cleaned.append(directory.relative_to(root).as_posix())
                except OSError:
                    pass
            try:
                folder.rmdir()
                directories_cleaned.append(folder.relative_to(root).as_posix())
            except OSError:
                pass
        if curated_entries:
            build_combined(paths)

    return {
        "dry_run": dry_run,
        "deleted_count": len(staged_ids),
        "deleted_ids": staged_ids,
        "files_deleted_count": len(deleted_files),
        "files_deleted": deleted_files,
        "orphan_files_deleted_count": orphan_count,
        "files_skipped_curated": skipped_curated,
        "files_skipped_external": external_count,
        "files_missing": missing_count,
        "directories_cleaned_count": len(directories_cleaned),
        "directories_cleaned": directories_cleaned,
        "combined_removed": combined_removed,
        "curated_count": len(curated_entries),
        "errors": errors,
    }


def _pdf_text(path: Path) -> str:
    import fitz
    with fitz.open(path) as document:
        return "\n\n".join(page.get_text("text") for page in document).strip()


def _xml_text(path: Path) -> tuple[str, str, str, str]:
    article = parse_elsevier_xml(path.read_text(encoding="utf-8", errors="replace"))
    return article.title or path.stem, normalize_doi(article.doi), normalize_pii(article.pii), article.markdown


def import_identified_item(paths: RepositoryPaths, identification: LiteratureIdentification, *, publisher: ElsevierApiConfig | None = None, extraction_mode: str = DEFAULT_EXTRACTION_MODE, http_client: Any = None, pdf_extractor: Any = None, keep_sources: bool = True, overwrite: bool = False) -> tuple[dict[str, Any], bool]:
    """Import one identified item; PDF use requires an explicit non-default mode."""
    extraction_mode = _validate_extraction_mode(extraction_mode)
    warnings: list[str] = []
    retrieval_status = "not_attempted"
    crossref_status = "not_attempted"
    identifier_attempts: list[dict[str, Any]] = []
    retrieval_error_message = ""
    lookup_doi = normalize_doi(identification.doi)
    lookup_pii = normalize_pii(identification.pii)
    identifier_metadata = {
        **identification.identifier_metadata,
        "doi": lookup_doi,
        "pii": lookup_pii,
        "sciencedirect_url": identification.sciencedirect_url,
    }
    available_identifiers = collect_article_identifiers(identifier_metadata)
    has_identifier = bool(available_identifiers)
    if extraction_mode != "pdf_only" and not has_identifier:
        message = _failure_message("not_eligible", has_sciencedirect_url=bool(identification.sciencedirect_url))
        if extraction_mode == "publisher_api_required":
            return create_metadata_only_entry(
                paths,
                identification,
                extraction_mode=extraction_mode,
                fulltext_status="structured_fulltext_unavailable",
                message=message,
                attempted_providers=[],
                provider_errors=[message],
                http_client=http_client,
                overwrite=overwrite,
            )
        warnings.append(message)
        retrieval_status = "not_eligible"
    if extraction_mode != "pdf_only" and has_identifier and (publisher is None or not publisher.api_key or not publisher.enabled):
        status = "disabled" if publisher is not None and publisher.api_key and not publisher.enabled else "not_configured"
        message = _failure_message(status)
        if extraction_mode == "publisher_api_required":
            return create_metadata_only_entry(
                paths,
                identification,
                extraction_mode=extraction_mode,
                fulltext_status="structured_fulltext_unavailable",
                message=message,
                attempted_providers=[{"provider": "elsevier", "status": status, "attempts": []}],
                provider_errors=[message],
                http_client=http_client,
                overwrite=overwrite,
            )
        warnings.append(message)
        retrieval_status = status
    if extraction_mode != "pdf_only" and publisher and publisher.api_key and has_identifier:
        paths.ensure()
        attempted_provider: dict[str, Any] = {"provider": "elsevier", "status": "not_attempted", "attempts": []}
        try:
            fulltext = ElsevierProvider(publisher, http_client=http_client).fetch_structured_fulltext(identifier_metadata)
            if fulltext.status != "success":
                attempts = fulltext.metadata.get("identifier_attempts") if isinstance(fulltext.metadata, dict) else []
                raise ArticleApiRetrievalFailed("; ".join(fulltext.errors) or "Elsevier structured full text was unavailable.", attempts)
            api_result = type("ElsevierProviderResult", (), {
                "retrieval": fulltext.metadata["retrieval"],
                "article": fulltext.metadata["article"],
                "used_identifier": fulltext.metadata["used_identifier"],
                "identifier_attempts": fulltext.metadata["identifier_attempts"],
                "api_retrieval_source": fulltext.metadata["api_retrieval_source"],
            })()
        except ArticleApiRetrievalFailed as exc:
            retrieval_status = str(exc.attempts[-1].get("status") or "failed") if exc.attempts else "failed"
            retrieval_error_message = str(exc)
            warnings.append(retrieval_error_message)
            identifier_attempts = exc.attempts
            attempted_provider = {"provider": "elsevier", "status": retrieval_status, "attempts": identifier_attempts}
        else:
            retrieval = api_result.retrieval
            article = api_result.article
            retrieval_status = retrieval.status
            identifier_attempts = api_result.identifier_attempts
            attempted_provider = {"provider": "elsevier", "status": retrieval_status, "attempts": identifier_attempts}
            metadata_source = "zotero+elsevier_xml" if identification.metadata_source == "zotero" else "elsevier_xml"
            entry, duplicate = upsert_markdown(
                paths,
                title=identification.title or article.title,
                markdown=article.markdown,
                doi=lookup_doi or article.doi,
                pii=lookup_pii or article.pii,
                source_type="elsevier_article_retrieval_api",
                overwrite=overwrite,
                metadata_fields={
                    "authors": identification.authors or article.authors,
                    "year": identification.year or article.year,
                    "journal": identification.journal or article.journal,
                    "item_type": identification.item_type,
                    "literature_type": _literature_type(identification.item_type),
                    "zotero_key": identification.zotero_key,
                    "sciencedirect_url": identification.sciencedirect_url,
                    "abstract": article.abstract,
                    "publication_date": article.publication_date,
                },
                provenance={
                    "extraction_mode": extraction_mode,
                    "metadata_source": metadata_source,
                    "content_source": "elsevier_xml",
                    "used_api_provider": "elsevier",
                    "attempted_providers": [attempted_provider],
                    "selected_provider": "elsevier",
                    "fulltext_source": "elsevier_article_retrieval_api",
                    "fulltext_format": "elsevier_xml",
                    "fulltext_status": "structured_fulltext_available",
                    "markdown_status": "markdown_validated",
                    "source_quality": "structured_xml",
                    "extraction_warnings": article.warnings,
                    "api_retrieval_status": retrieval_status,
                    "api_identifier_used_kind": api_result.used_identifier.kind,
                    "api_identifier_used_value": api_result.used_identifier.value,
                    "api_identifier_attempts": identifier_attempts,
                    "api_retrieval_source": api_result.api_retrieval_source,
                    "lookup_doi": lookup_doi or article.doi,
                    "lookup_pii": lookup_pii or article.pii,
                    "doi_used": lookup_doi or article.doi,
                    "pii_used": lookup_pii or article.pii,
                    "xml_retrieved": True,
                    "pdf_used": False,
                    "fallback_used": False,
                    "fallback_authorized_by": None,
                    "extraction_status": "success",
                    "extraction_errors": [],
                },
            )
            xml_path = paths.sources / f"{entry['canonical_id']}.elsevier.xml"
            xml_path.write_text(retrieval.xml_text or "", encoding="utf-8")
            metadata_path = paths.metadata / f"{entry['canonical_id']}.json"
            markdown_path = paths.markdown / f"{entry['canonical_id']}.md"
            entry["xml_artifact_path"] = _relative_artifact_path(paths, xml_path)
            entry["xml_markdown_artifact_path"] = _relative_artifact_path(paths, markdown_path)
            entry["auto_markdown_path"] = _relative_artifact_path(paths, markdown_path)
            entry["canonical_markdown_path"] = _relative_artifact_path(paths, markdown_path)
            entry["artifacts"] = _deduplicate_artifacts([
                *entry.get("artifacts", []),
                _artifact(entry["xml_artifact_path"], "elsevier_xml"),
                _artifact(entry["xml_markdown_artifact_path"], "elsevier_xml_markdown"),
            ])
            entry["generated_artifacts"] = [artifact["path"] for artifact in entry["artifacts"]]
            metadata_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return entry, duplicate

    if extraction_mode == "publisher_api_required":
        message = retrieval_error_message or _failure_message(retrieval_status, has_sciencedirect_url=bool(identification.sciencedirect_url))
        message = f"{message} No structured full text was staged. Please upload structured Markdown manually, or explicitly approve PDF fallback."
        return create_metadata_only_entry(
            paths,
            identification,
            extraction_mode=extraction_mode,
            fulltext_status="structured_fulltext_unavailable" if retrieval_status not in {"http_401", "http_403", "http_429"} else retrieval_status,
            message=message,
            attempted_providers=[{"provider": "elsevier", "status": retrieval_status, "attempts": identifier_attempts}],
            provider_errors=warnings or [message],
            http_client=http_client,
            overwrite=overwrite,
        )

    crossref = None
    if lookup_doi and not (identification.title and identification.authors and identification.year and identification.journal):
        crossref = retrieve_crossref_metadata(lookup_doi, http_client=http_client)
        crossref_status = crossref.status

    pdf_path = Path(identification.pdf_path) if identification.pdf_path else None
    if not pdf_path or not pdf_path.is_file():
        message = f"No local PDF was available for the explicitly selected {extraction_mode} mode."
        raise LiteratureExtractionError(message, _failure_diagnostics(extraction_mode, retrieval_status, message, doi=lookup_doi, pii=lookup_pii))
    fallback_used = extraction_mode == "pdf_fallback_allowed"
    if fallback_used:
        warnings.append("Publisher XML was unavailable; PDF extraction was used as a fallback after explicit authorization.")
    extractor = pdf_extractor or _pdf_text
    body = extractor(pdf_path)
    if not body:
        raise ValueError("PDF fallback contains no extractable text.")
    detected_doi, detected_pii = extract_identifiers(body)
    entry, duplicate = upsert_markdown(
        paths,
        title=identification.title or (crossref.title if crossref else None) or title_from_text(body, pdf_path.stem),
        markdown=body,
        doi=lookup_doi or detected_doi,
        pii=lookup_pii or detected_pii,
        source_type="pdf_fallback",
        source_path=pdf_path,
        overwrite=overwrite,
        metadata_fields={
            "authors": identification.authors or (crossref.authors if crossref else []),
            "year": identification.year or (crossref.year if crossref else None),
            "journal": identification.journal or (crossref.journal if crossref else None),
            "item_type": identification.item_type,
            "literature_type": _literature_type(identification.item_type),
            "zotero_key": identification.zotero_key,
            "sciencedirect_url": identification.sciencedirect_url,
        },
        provenance={
            "extraction_mode": extraction_mode,
            "metadata_source": (f"{identification.metadata_source}+crossref" if crossref and crossref.status == "success" and identification.metadata_source != "manual" else "crossref" if crossref and crossref.status == "success" else identification.metadata_source if identification.metadata_source != "manual" else "pdf_heuristic"),
            "content_source": "pdf_extraction",
            "used_api_provider": "elsevier" if extraction_mode != "pdf_only" else None,
            "extraction_warnings": warnings,
            "api_retrieval_status": retrieval_status,
            "lookup_doi": lookup_doi or detected_doi,
            "lookup_pii": lookup_pii or detected_pii,
            "doi_used": lookup_doi or detected_doi,
            "pii_used": lookup_pii or detected_pii,
            "xml_retrieved": False,
            "pdf_used": True,
            "fallback_used": fallback_used,
            "fallback_authorized_by": f"literature_extraction_mode={extraction_mode}",
            "extraction_status": "success_with_fallback" if fallback_used else "success",
            "extraction_errors": warnings,
            "crossref_retrieval_status": crossref_status,
        },
    )
    if keep_sources:
        destination = paths.sources / f"{entry['canonical_id']}{pdf_path.suffix.lower()}"
        if pdf_path.resolve() != destination.resolve():
            shutil.copy2(pdf_path, destination)
        metadata_path = paths.metadata / f"{entry['canonical_id']}.json"
        markdown_path = paths.markdown / f"{entry['canonical_id']}.md"
        entry["pdf_fallback_markdown_path"] = _relative_artifact_path(paths, markdown_path)
        entry["artifacts"] = _deduplicate_artifacts([
            *entry.get("artifacts", []),
            _artifact(_relative_artifact_path(paths, destination), "pdf_source_copy"),
            _artifact(entry["pdf_fallback_markdown_path"], "pdf_fallback_markdown"),
        ])
        entry["generated_artifacts"] = [artifact["path"] for artifact in entry["artifacts"]]
        metadata_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        metadata_path = paths.metadata / f"{entry['canonical_id']}.json"
        entry["generated_artifacts"] = [artifact["path"] for artifact in entry.get("artifacts", [])]
        metadata_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry, duplicate


def test_publisher_api(paths: RepositoryPaths, identification: LiteratureIdentification, *, publisher: ElsevierApiConfig, http_client: Any = None, write_artifacts: bool = True) -> dict[str, Any]:
    """Test Elsevier XML retrieval without reading or creating any PDF artifact."""
    lookup_doi = normalize_doi(identification.doi)
    lookup_pii = normalize_pii(identification.pii)
    try:
        api_result = retrieve_article_via_api_with_identifier_fallback(
            {**identification.identifier_metadata, "doi": lookup_doi, "pii": lookup_pii, "sciencedirect_url": identification.sciencedirect_url},
            publisher,
            http_client=http_client,
        )
    except ArticleApiRetrievalFailed as exc:
        status = str(exc.attempts[-1].get("status") or "failed") if exc.attempts else "failed"
        raise LiteratureExtractionError(str(exc), _failure_diagnostics(DEFAULT_EXTRACTION_MODE, status, str(exc), doi=lookup_doi, pii=lookup_pii, attempts=exc.attempts)) from exc
    retrieval = api_result.retrieval
    article = api_result.article
    markdown_path = None
    xml_path = None
    if write_artifacts:
        test_dir = paths.root / "api_tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_id = canonical_id(pii=lookup_pii or article.pii, doi=lookup_doi or article.doi, title=article.title)
        markdown_path = test_dir / f"{test_id}.md"
        xml_path = test_dir / f"{test_id}.xml"
        markdown_path.write_text(clean_llm_markdown(article.markdown, title=article.title, pii=lookup_pii or article.pii or "", doi=lookup_doi or article.doi or ""), encoding="utf-8")
        xml_path.write_text(retrieval.xml_text, encoding="utf-8")
    return {
        "api_provider": "elsevier",
        "request_status": retrieval.status,
        "status_code": retrieval.status_code,
        "title": article.title,
        "authors": article.authors,
        "journal": article.journal,
        "year": article.year,
        "doi": lookup_doi or article.doi,
        "pii": lookup_pii or article.pii,
        "section_count": article.section_count,
        "reference_count": article.reference_count,
        "xml_retrieved": True,
        "pdf_used": False,
        "api_identifier_used_kind": api_result.used_identifier.kind,
        "api_identifier_used_value": api_result.used_identifier.value,
        "api_identifier_attempts": api_result.identifier_attempts,
        "api_retrieval_source": api_result.api_retrieval_source,
        "markdown_path": str(markdown_path) if markdown_path else None,
        "xml_path": str(xml_path) if xml_path else None,
    }


def import_directory(paths: RepositoryPaths, source_dir: Path, *, source_type: str, extraction_mode: str = DEFAULT_EXTRACTION_MODE, keep_sources: bool = True, overwrite: bool = False) -> ImportResult:
    extraction_mode = _validate_extraction_mode(extraction_mode)
    if extraction_mode == "publisher_api_required":
        raise LiteratureExtractionError(
            "Directory/PDF extraction is disabled in publisher_api_required mode. Import identified Zotero records through the publisher API, or explicitly select pdf_fallback_allowed/pdf_only.",
            _failure_diagnostics(extraction_mode, "publisher_api_required", "PDF extraction was not authorized."),
        )
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Literature source directory was not found: {source_dir}")
    files = sorted((path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".md"}), key=lambda path: ({".xml": 0, ".md": 1, ".pdf": 2}[path.suffix.lower()], str(path).casefold()))
    result = ImportResult(files_scanned=len(files), failures=[])
    for source in files:
        try:
            if source.suffix.lower() == ".xml":
                title, doi, pii, body = _xml_text(source)
                article = parse_elsevier_xml(source.read_text(encoding="utf-8", errors="replace"))
                metadata_fields = {"authors": article.authors, "year": article.year, "journal": article.journal, "abstract": article.abstract, "publication_date": article.publication_date}
                provenance = {"extraction_mode": extraction_mode, "metadata_source": "elsevier_xml", "content_source": "elsevier_xml", "used_api_provider": None, "extraction_warnings": article.warnings, "api_retrieval_status": "local_xml", "lookup_doi": doi, "lookup_pii": pii, "doi_used": doi, "pii_used": pii, "xml_retrieved": True, "pdf_used": False, "fallback_used": False, "fallback_authorized_by": f"literature_extraction_mode={extraction_mode}", "extraction_status": "success", "extraction_errors": []}
            else:
                body = _pdf_text(source) if source.suffix.lower() == ".pdf" else source.read_text(encoding="utf-8", errors="replace")
                if not body:
                    raise ValueError("Source contains no extractable text")
                doi, pii = extract_identifiers(body)
                title = title_from_text(body, source.stem)
                metadata_fields = {}
                pdf_used = source.suffix.lower() == ".pdf"
                fallback_used = pdf_used and extraction_mode == "pdf_fallback_allowed"
                provenance = {"extraction_mode": extraction_mode, "metadata_source": "pdf_heuristic" if pdf_used else "manual", "content_source": "pdf_extraction" if pdf_used else "provided_markdown", "used_api_provider": None, "extraction_warnings": ["PDF extraction was explicitly authorized by the selected extraction mode."] if pdf_used else [], "api_retrieval_status": "not_attempted", "lookup_doi": doi, "lookup_pii": pii, "doi_used": doi, "pii_used": pii, "xml_retrieved": False, "pdf_used": pdf_used, "fallback_used": fallback_used, "fallback_authorized_by": f"literature_extraction_mode={extraction_mode}", "extraction_status": "success_with_fallback" if fallback_used else "success", "extraction_errors": []}
            entry, duplicate = upsert_markdown(paths, title=title, markdown=body, doi=doi, pii=pii, source_type=source_type, source_path=source, overwrite=overwrite, metadata_fields=metadata_fields, provenance=provenance)
            if keep_sources:
                destination = paths.sources / f"{entry['canonical_id']}{source.suffix.lower()}"
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                metadata_path = paths.metadata / f"{entry['canonical_id']}.json"
                entry["artifacts"] = _deduplicate_artifacts([
                    *entry.get("artifacts", []),
                    _artifact(_relative_artifact_path(paths, destination), "source_copy"),
                ])
                entry["generated_artifacts"] = [artifact["path"] for artifact in entry["artifacts"]]
                metadata_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result.duplicates += int(duplicate)
            result.imported += int(not duplicate)
        except Exception as exc:
            result.failed += 1
            result.failures.append({"path": str(source), "error": str(exc)})
    result.combined_count = build_combined(paths)
    result.combined_output_file = str(paths.combined)
    return result


def build_combined(paths: RepositoryPaths) -> int:
    """Build downstream context from human-curated entries only."""
    paths.ensure()
    blocks, seen = [], set()
    for item in list_curated_entries(paths):
        identity = normalize_pii(item.get("pii")) or normalize_doi(item.get("doi")) or normalize_title(item.get("title"))
        source = paths.curated_markdown / f"{item['canonical_id']}.md"
        if not identity or identity in seen or not source.exists():
            continue
        seen.add(identity)
        if blocks:
            blocks.extend(["", "---", ""])
        blocks.append(source.read_text(encoding="utf-8", errors="replace").strip())
    paths.combined.write_text("\n".join(blocks).rstrip() + ("\n" if blocks else ""), encoding="utf-8")
    return len(seen)


def duplicate_report(paths: RepositoryPaths) -> list[list[dict[str, Any]]]:
    groups, claimed = [], set()
    entries = list_entries(paths)
    for index, left in enumerate(entries):
        if left["canonical_id"] in claimed:
            continue
        left_values = {normalize_doi(left.get("doi")), normalize_pii(left.get("pii")), normalize_title(left.get("title"))} - {""}
        group = [left]
        for right in entries[index + 1:]:
            right_values = {normalize_doi(right.get("doi")), normalize_pii(right.get("pii")), normalize_title(right.get("title"))} - {""}
            if left_values & right_values:
                group.append(right)
        if len(group) > 1:
            groups.append(group)
            claimed.update(item["canonical_id"] for item in group)
    return groups


def deduplicate(paths: RepositoryPaths, *, apply: bool = False) -> dict[str, Any]:
    groups = duplicate_report(paths)
    report = {"dry_run": not apply, "duplicate_groups": [[item["canonical_id"] for item in group] for group in groups], "suspected_duplicates": sum(len(group) - 1 for group in groups), "backup": None}
    if not apply or not groups:
        return report
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = paths.backups / f"deduplicate-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    for folder in (paths.sources, paths.markdown, paths.metadata):
        if folder.exists():
            shutil.copytree(folder, backup / folder.name, dirs_exist_ok=True)
    for group in groups:
        primary = max(group, key=lambda item: (bool(item.get("pii")), bool(item.get("doi"))))
        text = (paths.markdown / f"{primary['canonical_id']}.md").read_text(encoding="utf-8", errors="replace")
        kept, _ = upsert_markdown(paths, title=primary["title"], markdown=text, doi=primary.get("doi"), pii=primary.get("pii"), source_type=primary.get("source_type") or "deduplication", overwrite=True)
        for item in group:
            if item["canonical_id"] != kept["canonical_id"]:
                for obsolete in (paths.markdown / f"{item['canonical_id']}.md", paths.metadata / f"{item['canonical_id']}.json"):
                    if obsolete.exists():
                        obsolete.unlink()
    build_combined(paths)
    report["backup"] = str(backup)
    return report


def reset_repository(paths: RepositoryPaths) -> dict[str, Any]:
    root = paths.root.resolve()
    if root == Path(root.anchor) or len(root.parts) < 3:
        raise ValueError(f"Refusing to reset unsafe literature path: {root}")
    deleted = [str(path) for path in root.iterdir()] if root.exists() else []
    if root.exists():
        for path in root.iterdir():
            path.unlink() if path.is_symlink() or path.is_file() else shutil.rmtree(path)
    paths.ensure()
    return {"ok": True, "path": str(root), "deleted": deleted}


def migrate_old(paths: RepositoryPaths, *, apply: bool = False) -> dict[str, Any]:
    files = [path for folder in (paths.root / "papers", paths.root / "Markdown", paths.root / "clean_markdown", paths.root / "llm_context") if folder.exists() for path in folder.glob("*.md")]
    plan = []
    for source in sorted(set(files)):
        text = source.read_text(encoding="utf-8", errors="replace")
        doi, pii = extract_identifiers(text)
        title = title_from_text(text, source.stem)
        plan.append({"source": str(source), "target": f"markdown/{canonical_id(pii=pii, doi=doi, title=title)}.md", "title": title, "doi": doi or None, "pii": pii or None, "metadata_preserved": sorted(CURATION_FIELDS)})
    report: dict[str, Any] = {"dry_run": not apply, "old_files_found": len(plan), "files": plan, "backup": None, "migrated": 0}
    if not apply or not plan:
        return report
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup, archive = paths.backups / f"migration-{stamp}", paths.archive / f"legacy-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    for item in plan:
        source = Path(item["source"])
        relative = source.relative_to(paths.root)
        (backup / relative.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup / relative)
        upsert_markdown(paths, title=item["title"], markdown=source.read_text(encoding="utf-8", errors="replace"), doi=item["doi"], pii=item["pii"], source_type="legacy_migration")
        destination = archive / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        report["migrated"] += 1
    build_combined(paths)
    report.update(backup=str(backup), archive=str(archive))
    return report


def write_project_settings(paths: RepositoryPaths, **updates: Any) -> dict[str, Any]:
    path = paths.root / "settings.json"
    current = _read_json(path)
    current.update({key: value for key, value in updates.items() if value is not None})
    current.setdefault("keep_temporary_pdfs", True)
    current.setdefault("overwrite_existing_markdown", False)
    current.setdefault("preserve_curated_metadata", True)
    paths.ensure()
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return current
