from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import get_settings


LOGGER = logging.getLogger(__name__)
REFERENCE_HEADINGS = {"references", "bibliography", "literature_cited"}
SCIENTIFIC_HEADINGS = {
    "abstract",
    "summary",
    "introduction",
    "background",
    "methods",
    "methodology",
    "materials_and_methods",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
}


@dataclass(frozen=True)
class LiteratureResetResult:
    """Result returned by the literature repository reset operation."""

    ok: bool
    path: Path
    deleted: list[str] = field(default_factory=list)
    message: str = ""
    error: str | None = None


@dataclass(frozen=True)
class LiteratureRepositoryLoadResult:
    """Valid LLM-ready Markdown papers loaded from disk plus skipped-file diagnostics."""

    papers: list[dict[str, Any]]
    loaded_files: list[Path] = field(default_factory=list)
    skipped_files: list[dict[str, str]] = field(default_factory=list)


def reset_literature_repository(path: Path | None = None) -> LiteratureResetResult:
    """Clear the configured literature directory, or an explicitly supplied repository path."""
    repository_path = Path(path or get_settings().literature_base_dir)
    deleted: list[str] = []
    try:
        _assert_safe_reset_target(repository_path)
        if repository_path.exists():
            deleted.extend(_clear_directory_contents(repository_path))
        repository_path.mkdir(parents=True, exist_ok=True)
        message = f"Reset literature directory at {repository_path}; removed {len(deleted)} item(s)."
        LOGGER.info(message)
        return LiteratureResetResult(ok=True, path=repository_path, deleted=deleted, message=message)
    except (OSError, ValueError) as exc:
        message = f"Could not reset literature directory at {repository_path}: {exc}"
        LOGGER.exception(message)
        return LiteratureResetResult(
            ok=False,
            path=repository_path,
            deleted=deleted,
            message=message,
            error=str(exc),
        )


def _assert_safe_reset_target(path: Path) -> None:
    resolved = path.resolve()
    if not str(path):
        raise ValueError("Literature reset path is empty.")
    if resolved == Path(resolved.anchor):
        raise ValueError(f"Refusing to reset filesystem root: {path}")
    if resolved.name in {"", ".", ".."}:
        raise ValueError(f"Refusing to reset unsafe literature path: {path}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _clear_directory_contents(path: Path) -> list[str]:
    root = path.resolve()
    deleted: list[str] = []
    for item in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        deleted.append(str(item))
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
            continue
        if child.is_dir():
            resolved_child = child.resolve()
            if not _is_relative_to(resolved_child, root):
                raise ValueError(f"Refusing to follow directory outside literature reset target: {child}")
            shutil.rmtree(child)
    return deleted


def write_llm_ready_repository(
    payload: dict[str, Any],
    repository_path: Path | None = None,
) -> list[Path]:
    """Write one compact LLM-ready Markdown file per paper."""
    root = Path(repository_path or get_settings().literature_repository_path)
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for paper in payload.get("papers") or []:
        llm_paper = paper_to_llm_ready_json(paper)
        path = save_literature_markdown(llm_paper, root)
        written.append(path)
    LOGGER.info("Wrote %s LLM-ready literature Markdown file(s) to %s", len(written), root)
    return written


def load_llm_ready_repository(repository_path: Path | None = None) -> list[dict[str, Any]]:
    """Load all per-paper LLM-ready Markdown files from the repository."""
    return load_llm_ready_repository_with_diagnostics(repository_path).papers


def load_llm_ready_repository_with_diagnostics(
    repository_path: Path | None = None,
) -> LiteratureRepositoryLoadResult:
    """Load valid LLM-ready Markdown files while reporting malformed files."""
    root = Path(repository_path or get_settings().literature_repository_path)
    if not root.exists():
        return LiteratureRepositoryLoadResult(papers=[])
    papers = []
    loaded_files = []
    skipped_files = []
    for path in sorted(root.rglob("*.md")):
        try:
            paper = load_literature_markdown(path)
        except (OSError, ValueError) as exc:
            LOGGER.warning("Skipping invalid literature Markdown %s: %s", path, exc)
            skipped_files.append({"path": str(path), "error": str(exc)})
            continue
        paper["source_file"] = str(path)
        papers.append(paper)
        loaded_files.append(path)
    return LiteratureRepositoryLoadResult(
        papers=papers,
        loaded_files=loaded_files,
        skipped_files=skipped_files,
    )


def literature_context_for_entry_generation(repository_path: Path | None = None) -> tuple[str, LiteratureRepositoryLoadResult]:
    """Build generation context from all valid LLM-ready literature Markdown files."""
    result = load_llm_ready_repository_with_diagnostics(repository_path)
    if not result.papers:
        return "", result
    return combine_literature_markdown(result.papers), result


def save_literature_markdown(paper: dict[str, Any], repository_path: Path | None = None) -> Path:
    """Save one LLM-ready literature entry as Markdown with YAML front matter."""
    root = Path(repository_path or get_settings().literature_repository_path)
    root.mkdir(parents=True, exist_ok=True)
    normalized = _paper_with_id(paper)
    path = root / filesystem_safe_paper_filename(normalized)
    path.write_text(display_literature_markdown(normalized), encoding="utf-8")
    return path


def load_literature_markdown(path: Path) -> dict[str, Any]:
    """Load one Markdown literature entry and return metadata plus parsed content."""
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_front_matter(text)
    if not metadata:
        raise ValueError("Literature Markdown must include YAML front matter.")
    paper = {
        "id": metadata.get("id") or path.stem,
        "title": metadata.get("title") or "",
        "authors": metadata.get("authors") or [],
        "year": metadata.get("year"),
        "doi": metadata.get("doi") or "",
        "pmid": metadata.get("pmid") or "",
        "source": metadata.get("source") or "",
        "url": metadata.get("url") or "",
        "imported_at": metadata.get("imported_at") or "",
        "abstract": _markdown_section(body, "Abstract"),
        "notes": _markdown_section(body, "Notes"),
        "ontology_relevant_information": _markdown_section(body, "Extracted ontology-relevant information"),
        "sections": _sections_from_markdown(body),
        "markdown": text,
        "metadata": metadata,
    }
    _validate_llm_ready_paper(paper)
    return paper


def combine_literature_markdown(papers: list[dict[str, Any]]) -> str:
    """Combine loaded Markdown entries into the corpus passed to the LLM."""
    blocks = ["# Literature Corpus"]
    for index, paper in enumerate(papers, start=1):
        entry_id = paper.get("id") or paper.get("paper_id") or f"literature-{index}"
        source_file = paper.get("source_file") or filesystem_safe_paper_filename(paper)
        markdown = paper.get("markdown") or display_literature_markdown(paper)
        blocks.append(
            "\n".join(
                [
                    f"## Literature Entry: {entry_id}",
                    "",
                    f"Source file: `{Path(source_file).name}`",
                    "",
                    markdown.strip(),
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def display_literature_markdown(paper: dict[str, Any]) -> str:
    """Render a paper as curator-readable Markdown with YAML front matter."""
    normalized = _paper_with_id(paper)
    sections = _flatten_llm_sections(normalized.get("sections") or [])
    front_matter = _front_matter(
        {
            "id": normalized.get("id"),
            "title": normalized.get("title"),
            "authors": normalized.get("authors") or [],
            "year": normalized.get("year"),
            "doi": normalized.get("doi"),
            "pmid": normalized.get("pmid"),
            "source": normalized.get("source") or "Ontology Curation Assistant",
            "url": normalized.get("url"),
            "imported_at": normalized.get("imported_at") or datetime.now(timezone.utc).isoformat(),
        }
    )
    body = [
        front_matter,
        "",
        f"# {normalized.get('title') or 'Untitled literature record'}",
        "",
        "## Abstract",
        "",
        normalized.get("abstract") or "",
        "",
        "## Notes",
        "",
        normalized.get("notes") or "",
        "",
        "## Extracted ontology-relevant information",
        "",
    ]
    for section in sections:
        heading = section.get("heading") or "Section"
        text = section.get("text") or ""
        if not text:
            continue
        body.extend([f"### {heading}", "", text, ""])
    if not sections:
        body.append(normalized.get("ontology_relevant_information") or "")
    return "\n".join(body).strip() + "\n"


def extract_llm_ready_paper(
    text: str,
    *,
    title: str | None = None,
    doi: str | None = None,
    authors: list[str] | None = None,
    year: int | str | None = None,
    abstract: str | None = None,
) -> dict[str, Any]:
    """Extract a deterministic LLM-ready paper record from raw text."""
    cleaned = clean_extracted_text(text)
    detected_doi = doi or _extract_doi(text) or _extract_doi(cleaned)
    detected_year = str(year or _extract_year(text) or _extract_year(cleaned) or "")
    detected_title = title or _extract_title(text) or _extract_title(cleaned)
    detected_authors = authors or _extract_authors(text) or _extract_authors(cleaned)
    sections = _parse_sections(cleaned)
    detected_abstract = abstract or _extract_abstract(sections)
    sections = [section for section in sections if _normalize_heading(section["heading"]) != "abstract"]
    lead_author = _lead_author(detected_authors)
    return {
        "title": detected_title,
        "doi": detected_doi or "",
        "citation": {
            "lead_author_year": ", ".join(part for part in [lead_author, detected_year] if part),
        },
        "abstract": detected_abstract or "",
        "sections": sections,
    }


def clean_extracted_text(text: str) -> str:
    """Normalize PDF-extracted text while preserving scientific wording."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stripped = [line.strip() for line in lines]
    counts = {line: stripped.count(line) for line in set(stripped) if line}
    kept: list[str] = []
    for line in stripped:
        if not line:
            kept.append("")
            continue
        if counts.get(line, 0) > 1 and len(line) < 120:
            continue
        if re.fullmatch(r"(?:page\s*)?\d+", line, flags=re.IGNORECASE):
            continue
        if re.search(r"copyright|all rights reserved|downloaded from|publisher", line, re.IGNORECASE):
            continue
        kept.append(line)

    merged = "\n".join(kept)
    merged = re.sub(r"(\w)-\n(\w)", r"\1\2", merged)
    merged = re.sub(r"[ \t]+", " ", merged)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    return merged.strip()


def paper_to_llm_ready_json(paper: dict[str, Any]) -> dict[str, Any]:
    """Convert an in-memory literature record to the per-paper Markdown schema."""
    citation = paper.get("citation") or {}
    metadata = paper.get("source_metadata") or paper.get("metadata") or {}
    zotero = paper.get("zotero") or {}
    content = paper.get("content") or {}
    if not content:
        content = {
            "sections": (paper.get("pdf_text") or {}).get("sections") or _section_map_to_sections(paper.get("sections") or {}),
            "canonical_source": (paper.get("pdf_text") or {}).get("source") or metadata.get("provider") or "",
        }
    sections = [
        _llm_section(section)
        for section in content.get("sections") or []
        if _normalize_heading(section.get("heading")) not in REFERENCE_HEADINGS
    ]
    sections = [section for section in sections if _normalize_heading(section["heading"]) != "abstract"]
    return {
        "id": paper.get("paper_id") or paper.get("id") or zotero.get("item_key") or "",
        "title": paper.get("title") or citation.get("title") or "",
        "authors": paper.get("authors") or citation.get("authors") or [],
        "year": paper.get("year") or citation.get("year") or "",
        "doi": paper.get("doi") or citation.get("doi") or "",
        "pmid": metadata.get("pmid") or "",
        "source": metadata.get("provider") or metadata.get("source") or content.get("canonical_source") or "",
        "url": metadata.get("url") or "",
        "citation": {
            "lead_author_year": _lead_author_year(
                paper.get("authors") or citation.get("authors") or [],
                paper.get("year") or citation.get("year"),
            ),
        },
        "abstract": metadata.get("abstract") or _extract_abstract(content.get("sections") or []) or "",
        "sections": sections,
    }


def _section_map_to_sections(section_map: dict[str, Any]) -> list[dict[str, Any]]:
    sections = []
    for heading, text in section_map.items():
        if text:
            sections.append({"heading": str(heading).replace("_", " ").title(), "text": str(text), "subsections": []})
    return sections


def filesystem_safe_paper_filename(paper: dict[str, Any]) -> str:
    """Return a stable filesystem-safe Markdown filename for one paper."""
    doi = paper.get("doi")
    if doi:
        seed = f"doi-{doi}"
    elif paper.get("pmid"):
        seed = f"pmid-{paper.get('pmid')}"
    elif paper.get("id") or paper.get("paper_id"):
        seed = f"id-{paper.get('id') or paper.get('paper_id')}"
    else:
        seed = "-".join(
            part for part in [paper.get("title"), paper.get("citation", {}).get("lead_author_year")] if part
        )
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", seed).strip("-").lower()
    normalized = normalized[:90] or "paper"
    digest = hashlib.sha1(seed.casefold().encode("utf-8")).hexdigest()[:8]
    return f"{normalized}-{digest}.md"


def write_extracted_paper(
    text: str,
    repository_path: Path | None = None,
    **metadata: Any,
) -> Path:
    """Extract raw text and save it as one LLM-ready paper Markdown file."""
    root = Path(repository_path or get_settings().literature_repository_path)
    root.mkdir(parents=True, exist_ok=True)
    paper = extract_llm_ready_paper(text, **metadata)
    path = save_literature_markdown(paper, root)
    LOGGER.info("Wrote extracted LLM-ready paper Markdown to %s", path)
    return path


def _llm_section(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "heading": section.get("heading") or "",
        "text": _strip_reference_text(section.get("text") or ""),
        "subsections": [
            _llm_section(child)
            for child in section.get("subsections") or []
            if _normalize_heading(child.get("heading")) not in REFERENCE_HEADINGS
        ],
    }


def _parse_sections(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines()]
    heading_positions = [
        (index, _heading_text(line))
        for index, line in enumerate(lines)
        if _heading_text(line)
    ]
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    for position, (line_index, heading) in enumerate(heading_positions):
        normalized = _normalize_heading(heading)
        if normalized in REFERENCE_HEADINGS:
            break
        next_index = heading_positions[position + 1][0] if position + 1 < len(heading_positions) else len(lines)
        body = _body_text(lines[line_index + 1:next_index])
        level = _heading_level(lines[line_index])
        section = {"heading": heading, "text": body, "subsections": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack and level > stack[-1][0]:
            stack[-1][1]["subsections"].append(section)
        else:
            sections.append(section)
        stack.append((level, section))
    if not sections and text:
        sections.append({"heading": "Full text", "text": _strip_reference_text(text), "subsections": []})
    return sections


def _heading_text(line: str) -> str | None:
    if not line:
        return None
    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$", line)
    candidate = numbered.group(2).strip() if numbered else line.strip()
    normalized = _normalize_heading(candidate)
    if numbered and len(candidate) <= 120 and len(candidate.split()) <= 12:
        return candidate
    if normalized in SCIENTIFIC_HEADINGS or normalized in REFERENCE_HEADINGS:
        return candidate
    return None


def _heading_level(line: str) -> int:
    numbered = re.match(r"^(\d+(?:\.\d+)*)", line)
    return numbered.group(1).count(".") + 1 if numbered else 1


def _body_text(lines: list[str]) -> str:
    return _strip_reference_text(re.sub(r"\s+", " ", " ".join(line for line in lines if line)).strip())


def _strip_reference_text(text: str) -> str:
    return re.split(
        r"(?im)^\s*(references|bibliography|literature cited)\s*$",
        text,
        maxsplit=1,
    )[0].strip()


def _extract_doi(text: str) -> str | None:
    match = re.search(r"\b10\.\d{4,9}/[^\s,;]+", text, re.IGNORECASE)
    return match.group(0).rstrip(".") if match else None


def _extract_year(text: str) -> str | None:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    return match.group(0) if match else None


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and _normalize_heading(stripped) not in SCIENTIFIC_HEADINGS and not _extract_doi(stripped):
            return stripped
    return "Untitled literature record"


def _extract_authors(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2:
        candidate = lines[1]
        if "," in candidate or " and " in candidate.casefold():
            return re.split(r"\s+and\s+|;\s*", candidate)
    return []


def _lead_author(authors: list[str]) -> str:
    if not authors:
        return ""
    first = authors[0].strip()
    return first.split(",")[0].split()[-1] if first else ""


def _lead_author_year(authors: list[str], year: Any) -> str:
    return ", ".join(part for part in [_lead_author([str(author) for author in authors]), str(year or "")] if part)


def _extract_abstract(sections: list[dict[str, Any]]) -> str | None:
    for section in sections:
        if _normalize_heading(section.get("heading")) == "abstract":
            return section.get("text") or None
    return None


def _normalize_heading(value: Any) -> str:
    text = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s+", "", str(value or "").casefold())
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def repository_status(path: Path | None = None) -> dict[str, Any]:
    """Return a small status payload for the LLM-ready literature repository."""
    root = Path(path or get_settings().literature_repository_path)
    files = sorted(root.rglob("*.md")) if root.exists() else []
    return {
        "path": str(root),
        "exists": root.exists(),
        "paper_count": len(files),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _validate_llm_ready_paper(paper: Any) -> None:
    if not isinstance(paper, dict):
        raise ValueError("Literature Markdown must describe an object.")
    if not isinstance(paper.get("sections"), list):
        raise ValueError("Literature Markdown must contain a sections list.")
    citation = paper.get("citation") if isinstance(paper.get("citation"), dict) else {}
    if not any([paper.get("id"), paper.get("title"), paper.get("doi"), citation.get("lead_author_year")]):
        raise ValueError("Literature Markdown must identify the paper by id, title, DOI, or lead_author_year.")


def _flatten_llm_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        flattened.append(section)
        flattened.extend(_flatten_llm_sections(section.get("subsections") or []))
    return flattened


def _paper_with_id(paper: dict[str, Any]) -> dict[str, Any]:
    result = dict(paper)
    citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
    if not result.get("id"):
        seed = result.get("doi") or result.get("title") or citation.get("lead_author_year") or "literature"
        result["id"] = re.sub(r"[^A-Za-z0-9]+", "-", str(seed)).strip("-").lower()[:80] or "literature"
    if "authors" not in result:
        result["authors"] = result.get("authors") or []
    if "year" not in result:
        result["year"] = result.get("year") or ""
    return result


def _front_matter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if value in (None, ""):
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    front = text[4:end].strip("\n")
    body = text[end + len("\n---"):].lstrip("\n")
    return _parse_front_matter(front), body


def _parse_front_matter(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if current_list and line.startswith("  - "):
            result[current_list].append(_unquote_yaml_scalar(line[4:]))
            continue
        current_list = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            result[key] = []
            current_list = key
        else:
            result[key] = _unquote_yaml_scalar(value)
    return result


def _unquote_yaml_scalar(value: str) -> Any:
    text = value.strip()
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if re.fullmatch(r"\d{4}", text):
        return int(text)
    return text


def _markdown_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"(?ims)^##\s+{re.escape(heading)}\s*$\n?(.*?)(?=^##\s+|\Z)")
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def _sections_from_markdown(body: str) -> list[dict[str, Any]]:
    relevant = _markdown_section(body, "Extracted ontology-relevant information")
    if not relevant:
        return []
    matches = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", relevant))
    if not matches:
        return [{"heading": "Extracted ontology-relevant information", "text": relevant, "subsections": []}]
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(relevant)
        sections.append({"heading": match.group(1).strip(), "text": relevant[start:end].strip(), "subsections": []})
    return sections
