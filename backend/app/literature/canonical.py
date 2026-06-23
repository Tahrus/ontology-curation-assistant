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

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.I)
PII_RE = re.compile(r"S\d{4}[\s-]?\d{4}\s*\(\d{2}\)\s*\d{5}[\s-]?\d|S\d{16}", re.I)
CURATION_FIELDS = {"project_tags", "review_status", "curation", "annotations", "ontology_suggestions", "include_in_llm_extraction", "document_role", "requires_manual_review", "state"}
MANAGED_ARTIFACT_DIRS = {
    "sources", "markdown", "metadata", "raw", "clean", "context", "reports",
    "papers", "blocked", "combined", "raw_markdown", "clean_markdown",
    "llm_context", "metadata_reports", "rejected_or_review_required",
    "Markdown", "Paper-PDF",
}


def _relative_artifact_path(paths: "RepositoryPaths", path: Path) -> str:
    return path.resolve().relative_to(paths.root.resolve()).as_posix()


def _artifact(path: str, artifact_type: str, ownership: str = "staged") -> dict[str, str]:
    return {"path": path, "artifact_type": artifact_type, "ownership": ownership}


def _deduplicate_artifacts(artifacts: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("path"):
            unique[artifact["path"]] = artifact
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
        markdown = paths.markdown / f"{item.get('canonical_id', path.stem)}.md"
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


def upsert_markdown(paths: RepositoryPaths, *, title: str, markdown: str, doi: str | None = None, pii: str | None = None, source_type: str = "local_markdown", source_path: Path | None = None, overwrite: bool = False) -> tuple[dict[str, Any], bool]:
    paths.ensure()
    found_doi, found_pii = extract_identifiers(markdown)
    doi, pii = normalize_doi(doi) or found_doi, normalize_pii(pii) or found_pii
    previous = _existing(paths, doi, pii, title)
    old_id = str((previous or {}).get("canonical_id") or "")
    target_id = canonical_id(pii=pii or (previous or {}).get("pii"), doi=doi or (previous or {}).get("doi"), title=title)
    now = datetime.now(timezone.utc).isoformat()
    metadata = {**(previous or {}), "canonical_id": target_id, "title": title or (previous or {}).get("title") or "Untitled article", "pii": pii or (previous or {}).get("pii") or None, "doi": doi or (previous or {}).get("doi") or None, "source_type": source_type, "source_path": str(source_path) if source_path else (previous or {}).get("source_path"), "import_status": "staged", "curation_status": "needs_review", "duplicate_status": "canonical_reused" if previous else "unique", "pipeline_version": "oca-canonical-v2", "imported_at": now, "updated_at": now}
    metadata.setdefault("created_at", now)
    target = paths.markdown / f"{target_id}.md"
    old = paths.markdown / f"{old_id}.md" if old_id else None
    current = old.read_text(encoding="utf-8", errors="replace") if old and old.exists() else (target.read_text(encoding="utf-8", errors="replace") if target.exists() else "")
    candidate = clean_llm_markdown(markdown, title=metadata["title"], pii=metadata["pii"] or "", doi=metadata["doi"] or "")
    if overwrite or not current or len(candidate.split()) > len(current.split()):
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
    metadata_path = paths.metadata / f"{target_id}.json"
    metadata["artifacts"] = _deduplicate_artifacts([
        *(previous or {}).get("artifacts", []),
        _artifact(_relative_artifact_path(paths, target), "paper_markdown"),
        _artifact(_relative_artifact_path(paths, metadata_path), "metadata_json"),
    ])
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata, previous is not None


def _unique_tags(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in (values or []) if value.strip()))


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
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "xml")
    def value(*names: str) -> str:
        for name in names:
            node = soup.find(name)
            if node and node.get_text(" ", strip=True):
                return node.get_text(" ", strip=True)
        return ""
    title = value("dc:title", "ce:title", "title") or path.stem
    blocks = []
    if abstract := value("ce:abstract", "abstract"):
        blocks.extend(["## Abstract", "", abstract, ""])
    for section in soup.find_all(["ce:section", "section", "sec"]):
        heading = section.find(["ce:section-title", "title"])
        paragraphs = [node.get_text(" ", strip=True) for node in section.find_all(["ce:para", "p"])]
        if paragraphs:
            blocks.extend([f"## {heading.get_text(' ', strip=True) if heading else 'Section'}", "", "\n\n".join(paragraphs), ""])
    return title, normalize_doi(value("prism:doi", "doi")), normalize_pii(value("pii", "xocs:pii-unformatted", "prism:pii")), "\n".join(blocks) or soup.get_text("\n", strip=True)


def import_directory(paths: RepositoryPaths, source_dir: Path, *, source_type: str, keep_sources: bool = True, overwrite: bool = False) -> ImportResult:
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Literature source directory was not found: {source_dir}")
    files = sorted(path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".pdf", ".xml", ".md"})
    result = ImportResult(files_scanned=len(files), failures=[])
    for source in files:
        try:
            if source.suffix.lower() == ".xml":
                title, doi, pii, body = _xml_text(source)
            else:
                body = _pdf_text(source) if source.suffix.lower() == ".pdf" else source.read_text(encoding="utf-8", errors="replace")
                if not body:
                    raise ValueError("Source contains no extractable text")
                doi, pii = extract_identifiers(body)
                title = title_from_text(body, source.stem)
            entry, duplicate = upsert_markdown(paths, title=title, markdown=body, doi=doi, pii=pii, source_type=source_type, source_path=source, overwrite=overwrite)
            if keep_sources:
                destination = paths.sources / f"{entry['canonical_id']}{source.suffix.lower()}"
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                metadata_path = paths.metadata / f"{entry['canonical_id']}.json"
                entry["artifacts"] = _deduplicate_artifacts([
                    *entry.get("artifacts", []),
                    _artifact(_relative_artifact_path(paths, destination), "source_copy"),
                ])
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
