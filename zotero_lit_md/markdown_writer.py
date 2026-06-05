from __future__ import annotations

import json
from pathlib import Path

from zotero_lit_md.chunking import build_retrieval_chunks
from zotero_lit_md.diagnostics import build_claim_units
from zotero_lit_md.schema import ExtractedPaper, PaperMetadata, RetrievalChunk, SectionBlock
from zotero_lit_md.text_cleaning import paper_markdown_filename, path_text


def finalize_paper_layers(paper: ExtractedPaper) -> ExtractedPaper:
    paper_key = paper.metadata.zotero_item_key or paper.metadata.doi or "paper"
    if not paper.retrieval_chunks:
        paper.retrieval_chunks = build_retrieval_chunks(paper.sections, paper_key=paper_key)
    if not paper.claim_units:
        paper.claim_units = build_claim_units(paper.sections, paper_key=paper_key)
    return paper


def write_paper_markdown(
    paper: ExtractedPaper,
    output_dir: Path,
    *,
    json_sidecar: bool = False,
    overwrite: bool = False,
    existing_names: set[str] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    paper = finalize_paper_layers(paper)
    filename = paper_markdown_filename(
        year=paper.metadata.year,
        lead_author=paper.metadata.lead_author,
        title=paper.metadata.title,
        zotero_key=paper.metadata.zotero_item_key,
        existing=existing_names,
    )
    path = output_dir / filename
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {path}")
    path.write_text(render_paper_markdown(paper), encoding="utf-8")
    if json_sidecar:
        path.with_suffix(".json").write_text(
            json.dumps(paper.sidecar_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return path


def write_combined_corpus(paths: list[Path], output_dir: Path, *, overwrite: bool = False) -> Path:
    combined = output_dir / "combined_corpus.md"
    if combined.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {combined}")
    blocks = ["# Literature Corpus"]
    for path in paths:
        blocks.append(f"## Literature Entry: {path.stem}\n\nSource file: `{path.name}`\n\n{path.read_text(encoding='utf-8').strip()}")
    combined.write_text("\n\n---\n\n".join(blocks) + "\n", encoding="utf-8")
    return combined


def render_paper_markdown(paper: ExtractedPaper) -> str:
    metadata = paper.metadata
    diagnostics = paper.diagnostics
    sections = "\n\n".join(_render_section(section) for section in paper.sections)
    return "\n".join(
        [
            f"# {metadata.title or 'Untitled paper'}",
            "",
            "## LLM-ready full-text Markdown",
            "",
            "This Markdown file was generated from a Zotero-managed local PDF. Images are omitted. Figure captions, table text, equations, references, and article body text are retained where the PDF text layer exposed them. The layout was converted into a single reading order for LLM/RAG ingestion.",
            "",
            "## Minimal metadata",
            "",
            *_metadata_lines(metadata, diagnostics.extraction_status),
            "",
            "## Extraction diagnostics",
            "",
            *_diagnostic_lines(diagnostics),
            "",
            "## Abstract",
            "",
            metadata.abstract or "",
            "",
            "## Keywords",
            "",
            *[f"* {keyword}" for keyword in metadata.keywords],
            "" if metadata.keywords else "* ",
            "",
            "## Concept map for LLM routing",
            "",
            *_concept_map_lines(),
            "",
            "## Paper body",
            "",
            sections,
            "",
            "## Retrieval chunks",
            "",
            *[_render_chunk(chunk) for chunk in paper.retrieval_chunks],
            "",
            "## Claim units",
            "",
            *[_render_claim(claim) for claim in paper.claim_units],
            "",
        ]
    )


def _metadata_lines(metadata: PaperMetadata, status: str) -> list[str]:
    return [
        f"* **Title:** {metadata.title}",
        f"* **DOI:** {metadata.doi}",
        f"* **Citation:** {metadata.citation}",
        f"* **Authors:** {'; '.join(metadata.authors)}",
        f"* **Year:** {metadata.year}",
        f"* **Journal:** {metadata.journal}",
        f"* **Volume:** {metadata.volume}",
        f"* **Issue:** {metadata.issue}",
        f"* **Pages / Article number:** {metadata.pages_or_article_number}",
        f"* **Zotero item key:** {metadata.zotero_item_key}",
        f"* **Zotero attachment key:** {metadata.zotero_attachment_key}",
        f"* **Zotero collection:** {metadata.zotero_collection}",
        f"* **PDF filename:** {metadata.pdf_filename}",
        f"* **PDF path:** {path_text(metadata.pdf_path)}",
        "* **Images:** omitted",
        f"* **Extraction status:** {status}",
    ]


def _diagnostic_lines(diagnostics) -> list[str]:
    warnings = diagnostics.warnings or [""]
    return [
        f"* **PDF pages:** {diagnostics.pdf_pages}",
        f"* **Extracted characters:** {diagnostics.extracted_characters}",
        f"* **Text extraction method:** {diagnostics.text_extraction_method}",
        f"* **Detected layout:** {diagnostics.detected_layout}",
        f"* **Tables extracted:** {diagnostics.tables_extracted}",
        f"* **Equations extracted:** {diagnostics.equations_extracted}",
        f"* **References extracted:** {diagnostics.references_extracted}",
        "* **Warnings:**",
        "",
        *[f"  * {warning}" for warning in warnings],
    ]


def _concept_map_lines() -> list[str]:
    return [
        "* **Domain:** ",
        "* **Study type:** other",
        "* **Main system:** ",
        "* **Main process:** ",
        "* **Main methods:** ",
        "* **Main measurements:** ",
        "* **Main outputs:** ",
        "* **Key variables:** ",
        "* **Key models:** ",
        "* **Main contribution:** ",
        "* **Limitations:** ",
    ]


def _render_section(section: SectionBlock) -> str:
    heading = "#" * section.level
    parts = [f"{heading} {section.heading}", "", section.text.strip()]
    parts.extend(_render_section(child) for child in section.subsections)
    return "\n\n".join(part for part in parts if part)


def _render_chunk(chunk: RetrievalChunk) -> str:
    pages = _page_range(chunk.page_start, chunk.page_end)
    return "\n".join(
        [
            f"### Chunk {chunk.chunk_id}",
            "",
            f"* **Source section:** {' > '.join(chunk.heading_path)}",
            f"* **Pages:** {pages}",
            f"* **Approx tokens:** {chunk.approx_tokens}",
            f"* **Chunk type:** {chunk.chunk_type}",
            f"* **Key terms:** {', '.join(chunk.key_terms)}",
            "",
            chunk.text,
            "",
        ]
    )


def _render_claim(claim) -> str:
    return "\n".join(
        [
            f"* **Claim ID:** {claim.claim_id}",
            "",
            f"  * **Claim:** {claim.claim}",
            f"  * **Evidence section:** {claim.evidence_section}",
            f"  * **Pages:** {claim.pages}",
            f"  * **Type:** {claim.type}",
            "",
        ]
    )


def _page_range(start: int | None, end: int | None) -> str:
    if start is None and end is None:
        return ""
    if start == end or end is None:
        return str(start)
    return f"{start}-{end}"
