"""Compatibility wrapper for the project-scoped canonical literature pipeline.

The former BibPipelineCombined path is intentionally not imported here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.config import Settings, get_settings
from backend.app.literature.canonical import RepositoryPaths, build_combined, import_directory


@dataclass(frozen=True)
class LiteraturePipelineConfig:
    zotero_literature_storage_path: Path | None
    base_dir: Path
    pdf_dir: Path | None = None
    generated_md_dir: Path | None = None
    papers_dir: Path | None = None
    combined_output_file: Path | None = None
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
    skipped_paper_count: int = 0
    extraction_report_file: Path | None = None
    cleanup_report_file: Path | None = None


def literature_pipeline_config_from_settings(settings: Settings | None = None) -> LiteraturePipelineConfig:
    settings = settings or get_settings()
    base = Path(settings.literature_base_dir)
    return LiteraturePipelineConfig(
        zotero_literature_storage_path=Path(settings.zotero_literature_storage_path) if settings.zotero_literature_storage_path else None,
        base_dir=base,
        pdf_dir=base / "sources",
        generated_md_dir=base / "markdown",
        papers_dir=base / "markdown",
        combined_output_file=base / "combined_literature.md",
        fuzzy_min_score=settings.literature_fuzzy_min_score,
    )


def validate_pipeline_config(config: LiteraturePipelineConfig, *, require_source: bool = True) -> None:
    if require_source and config.zotero_literature_storage_path is None:
        raise ValueError("Zotero literature storage path is not configured.")
    if require_source and config.zotero_literature_storage_path and not config.zotero_literature_storage_path.exists():
        raise FileNotFoundError(f"Configured Zotero literature storage path was not found: {config.zotero_literature_storage_path}")
    if require_source and config.zotero_literature_storage_path and not config.zotero_literature_storage_path.exists():
        raise FileNotFoundError(f"Configured Zotero literature storage path was not found: {config.zotero_literature_storage_path}")
    if require_source and config.zotero_literature_storage_path and not config.zotero_literature_storage_path.exists():
        raise FileNotFoundError(f"Configured Zotero literature storage path was not found: {config.zotero_literature_storage_path}")
    if require_source and config.zotero_literature_storage_path and not config.zotero_literature_storage_path.is_dir():
        raise NotADirectoryError(f"Configured literature source is not a directory: {config.zotero_literature_storage_path}")
    RepositoryPaths.from_root(config.base_dir).ensure()


def discover_zotero_pdfs(source_dir: Path) -> list[Path]:
    return sorted(path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf")


def run_literature_pipeline(config: LiteraturePipelineConfig) -> LiteraturePipelineResult:
    validate_pipeline_config(config)
    assert config.zotero_literature_storage_path is not None
    result = import_directory(RepositoryPaths.from_root(config.base_dir), config.zotero_literature_storage_path, source_type="zotero_storage")
    if not result.files_scanned:
        raise ValueError(f"No PDF, XML, or Markdown files were found under {config.zotero_literature_storage_path}")
    return LiteraturePipelineResult(
        combined_output_file=Path(result.combined_output_file),
        copied_pdf_count=result.files_scanned - result.failed,
        converted_markdown_count=result.imported + result.duplicates,
        failed_pdf_count=result.failed,
        created_paper_markdown_count=result.imported,
        structured_markdown_count=result.imported + result.duplicates,
        combined_markdown_count=result.combined_count,
        skipped_paper_count=result.duplicates,
    )


def combine_markdown_files(papers_dir: Path, output_file: Path) -> int:
    paths = RepositoryPaths.from_root(output_file.parent)
    count = build_combined(paths)
    if paths.combined != output_file:
        output_file.write_text(paths.combined.read_text(encoding="utf-8"), encoding="utf-8")
    return count
