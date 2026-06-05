from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil

import sys
from backend.app.config import Settings, get_settings

app_dir = str(Path(__file__).resolve().parent.parent)
if app_dir not in sys.path:
    sys.path.append(app_dir)
from BibPipelineCombined import run_pipeline  # type: ignore[import-not-found]  # noqa: E402


PIPELINE_STAGE_ERROR = {
    "missing_storage": "Zotero literature storage path is not configured. Set it in Configuration.",
    "no_pdfs": "No PDF files were found under the configured Zotero literature storage path.",
    "copy_failed": "No PDFs were copied into the literature pipeline input folder.",
    "markdown_failed": "No Markdown files were generated from the copied PDFs.",
    "combine_failed": "No comprehensive combined literature Markdown file was generated.",
}


@dataclass(frozen=True)
class LiteraturePipelineConfig:
    zotero_literature_storage_path: Path | None
    base_dir: Path
    pdf_dir: Path
    generated_md_dir: Path
    papers_dir: Path
    combined_output_file: Path
    fuzzy_min_score: float = 0.82


@dataclass(frozen=True)
class LiteraturePipelineResult:
    combined_output_file: Path
    copied_pdf_count: int
    converted_markdown_count: int
    failed_pdf_count: int
    created_paper_markdown_count: int
    structured_markdown_count: int
    combined_markdown_count: int

def literature_pipeline_config_from_settings(
    settings: Settings | None = None,
) -> LiteraturePipelineConfig:
    """Build pipeline paths from application settings."""
    settings = settings or get_settings()
    base_dir = Path(settings.literature_base_dir)
    return LiteraturePipelineConfig(
        zotero_literature_storage_path=(
            Path(settings.zotero_literature_storage_path)
            if settings.zotero_literature_storage_path
            else None
        ),
        base_dir=base_dir,
        pdf_dir=Path(settings.literature_pdf_dir),
        generated_md_dir=Path(settings.literature_generated_md_dir),
        papers_dir=Path(settings.literature_repository_path),
        combined_output_file=Path(settings.literature_combined_output_file),
        fuzzy_min_score=settings.literature_fuzzy_min_score,
    )


def validate_pipeline_config(config: LiteraturePipelineConfig, *, require_source: bool = True) -> None:
    """Validate configured paths before a pipeline stage runs."""
    storage_path = config.zotero_literature_storage_path
    if require_source and storage_path is None:
        raise ValueError(
            "Zotero literature storage path is not configured. "
            "Set it in Configuration or OCA_ZOTERO_LITERATURE_STORAGE_PATH."
        )
    if storage_path is not None and require_source and not storage_path.exists():
        raise FileNotFoundError(
            "Configured Zotero literature storage path was not found: "
            f"{storage_path}. Set it in Configuration or OCA_ZOTERO_LITERATURE_STORAGE_PATH."
        )
    if storage_path is not None and require_source and not storage_path.is_dir():
        raise NotADirectoryError(
            "Configured Zotero literature storage path is not a directory: "
            f"{storage_path}."
        )
    for directory in [config.base_dir, config.pdf_dir, config.generated_md_dir, config.papers_dir]:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(f"Could not create literature directory {directory}: {exc}") from exc


def discover_zotero_pdfs(source_dir: Path) -> list[Path]:
    """Return all Zotero storage PDFs discovered by the original recursive import flow."""
    return sorted(path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "zotero-literature"


def _quote_yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _title_from_generated_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or path.stem
    return path.stem.replace("_", " ").replace("-", " ").strip() or "Untitled literature record"


def _extract_title_from_paper_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("title:"):
            return stripped.split(":", 1)[1].strip().strip('"') or path.stem
        if stripped.startswith("# "):
            return stripped[2:].strip() or path.stem
    return path.stem


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _clear_pipeline_working_dir(path: Path, *, base_dir: Path) -> None:
    """Clear generated pipeline inputs/outputs before import so repeated runs stay idempotent."""
    target = path.resolve()
    base = base_dir.resolve()
    if not _is_relative_to(target, base):
        raise ValueError(f"Refusing to clear literature pipeline folder outside base directory: {path}")
    if target == base:
        raise ValueError(f"Refusing to clear literature base directory as a pipeline working folder: {path}")
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)


def _count_files(path: Path, suffix: str) -> int:
    if not path.exists():
        return 0
    suffix = suffix.casefold()
    return len([candidate for candidate in path.iterdir() if candidate.is_file() and candidate.suffix.casefold() == suffix])


def create_paper_markdown_files_from_generated(generated_md_dir: Path, papers_dir: Path) -> int:
    """Create repository Markdown records for generated Zotero PDFs with no existing paper file."""
    papers_dir.mkdir(parents=True, exist_ok=True)
    existing_titles: set[str] = set()
    for paper_path in sorted(papers_dir.glob("*.md")):
        title = _extract_title_from_paper_markdown(paper_path)
        if title:
            existing_titles.add(_normalize_title(title))

    created = 0
    for generated_path in sorted(generated_md_dir.glob("*.md")):
        generated_text = generated_path.read_text(encoding="utf-8", errors="replace").strip()
        if not generated_text:
            continue
        title = _title_from_generated_markdown(generated_path)
        normalized_title = _normalize_title(title)
        if normalized_title in existing_titles:
            continue

        digest = hashlib.sha1(str(generated_path).encode("utf-8")).hexdigest()[:10]
        output_path = papers_dir / f"{_slug(title)}-{digest}.md"
        imported_at = datetime.now(timezone.utc).isoformat()
        front_matter = "\n".join(
            [
                "---",
                f"id: {_quote_yaml(f'zotero-pdf-{digest}')}",
                f"title: {_quote_yaml(title)}",
                "source: \"Zotero literature pipeline\"",
                f"source_pdf_markdown: {_quote_yaml(str(generated_path))}",
                f"imported_at: {_quote_yaml(imported_at)}",
                "---",
            ]
        )
        output_path.write_text(f"{front_matter}\n\n{generated_text}\n", encoding="utf-8")
        existing_titles.add(normalized_title)
        created += 1
    return created


def run_literature_pipeline(config: LiteraturePipelineConfig) -> LiteraturePipelineResult:
    """Run the configured BibPipelineCombined.py workflow."""
    validate_pipeline_config(config, require_source=True)
    if config.zotero_literature_storage_path is None:
        raise ValueError(PIPELINE_STAGE_ERROR["missing_storage"])
    discovered_pdfs = discover_zotero_pdfs(config.zotero_literature_storage_path)
    if not discovered_pdfs:
        raise ValueError(
            f"{PIPELINE_STAGE_ERROR['no_pdfs']} Path: {config.zotero_literature_storage_path}"
        )

    _clear_pipeline_working_dir(config.pdf_dir, base_dir=config.base_dir)
    _clear_pipeline_working_dir(config.generated_md_dir, base_dir=config.base_dir)

    run_pipeline(
        zotero_storage_dir=config.zotero_literature_storage_path,
        base_dir=config.base_dir,
        pdf_dir=config.pdf_dir,
        generated_md_dir=config.generated_md_dir,
        papers_dir=config.papers_dir,
        combined_output_file=config.combined_output_file,
        skip_structure=True,
        skip_combine=True,
    )

    copied_pdf_count = _count_files(config.pdf_dir, ".pdf")
    converted_markdown_count = _count_files(config.generated_md_dir, ".md")
    failed_pdf_count = max(0, copied_pdf_count - converted_markdown_count)

    if copied_pdf_count == 0:
        raise ValueError(f"{PIPELINE_STAGE_ERROR['copy_failed']} Folder: {config.pdf_dir}")
    if converted_markdown_count == 0:
        raise ValueError(
            f"{PIPELINE_STAGE_ERROR['markdown_failed']} PDF folder: {config.pdf_dir}; "
            f"Markdown folder: {config.generated_md_dir}; failures: {failed_pdf_count}."
        )

    created_paper_markdown_count = create_paper_markdown_files_from_generated(
        config.generated_md_dir,
        config.papers_dir,
    )

    # Get paper markdown files before structuring to detect changes
    papers_before = {}
    for p in config.papers_dir.glob("*.md"):
        try:
            papers_before[p] = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    run_pipeline(
        zotero_storage_dir=config.zotero_literature_storage_path,
        base_dir=config.base_dir,
        pdf_dir=config.pdf_dir,
        generated_md_dir=config.generated_md_dir,
        papers_dir=config.papers_dir,
        combined_output_file=config.combined_output_file,
        fuzzy_min_score=config.fuzzy_min_score,
        skip_import=True,
        skip_convert=True,
    )

    structured_markdown_count = 0
    for p in config.papers_dir.glob("*.md"):
        try:
            content_after = p.read_text(encoding="utf-8", errors="replace")
            if p not in papers_before or papers_before[p] != content_after:
                structured_markdown_count += 1
        except Exception:
            pass

    combined_markdown_count = len(list(config.papers_dir.glob("*.md")))
    if combined_markdown_count == 0:
        raise ValueError(f"{PIPELINE_STAGE_ERROR['combine_failed']} Folder: {config.papers_dir}")
    if not config.combined_output_file.exists():
        raise ValueError(f"{PIPELINE_STAGE_ERROR['combine_failed']} File: {config.combined_output_file}")

    return LiteraturePipelineResult(
        combined_output_file=config.combined_output_file,
        copied_pdf_count=copied_pdf_count,
        converted_markdown_count=converted_markdown_count,
        failed_pdf_count=failed_pdf_count,
        created_paper_markdown_count=created_paper_markdown_count,
        structured_markdown_count=structured_markdown_count,
        combined_markdown_count=combined_markdown_count,
    )


def combine_markdown_files(papers_dir: Path, output_file: Path) -> int:
    """Compatibility helper that delegates combining to BibPipelineCombined.run_pipeline."""
    run_pipeline(
        base_dir=papers_dir.parent,
        zotero_storage_dir=papers_dir.parent,
        papers_dir=papers_dir,
        combined_output_file=output_file,
        skip_import=True,
        skip_convert=True,
        skip_structure=True,
    )
    return _count_files(papers_dir, ".md")
