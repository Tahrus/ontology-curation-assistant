from __future__ import annotations

import re

from zotero_lit_md.schema import RetrievalChunk, SectionBlock
from zotero_lit_md.text_cleaning import chunk_type_for_heading


def approx_token_count(text: str) -> int:
    return max(1, int(len(re.findall(r"\S+", text or "")) / 0.75))


def key_terms(text: str, *, limit: int = 10) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{4,}", text or "")
    ignored = {
        "which",
        "there",
        "their",
        "these",
        "those",
        "using",
        "therefore",
        "paper",
        "study",
        "result",
    }
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for word in words:
        key = word.casefold()
        if key in ignored:
            continue
        counts[key] = counts.get(key, 0) + 1
        display.setdefault(key, word)
    return [display[key] for key, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def build_retrieval_chunks(
    sections: list[SectionBlock],
    *,
    paper_key: str,
    target_tokens: int = 1200,
    max_tokens: int = 1500,
) -> list[RetrievalChunk]:
    chunks: list[RetrievalChunk] = []
    counter = 1
    for section, heading_path in _iter_sections(sections, []):
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", section.text or "") if paragraph.strip()]
        if not paragraphs and not section.subsections:
            continue
        current: list[str] = []
        for paragraph in paragraphs:
            candidate = "\n\n".join([*current, paragraph])
            if current and approx_token_count(candidate) > max_tokens:
                chunks.append(_chunk(counter, paper_key, heading_path, section, "\n\n".join(current)))
                counter += 1
                current = [paragraph]
            else:
                current.append(paragraph)
            if approx_token_count("\n\n".join(current)) >= target_tokens:
                chunks.append(_chunk(counter, paper_key, heading_path, section, "\n\n".join(current)))
                counter += 1
                current = []
        if current:
            chunks.append(_chunk(counter, paper_key, heading_path, section, "\n\n".join(current)))
            counter += 1
    return chunks


def _chunk(
    counter: int,
    paper_key: str,
    heading_path: list[str],
    section: SectionBlock,
    text: str,
) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=f"{paper_key}_chunk_{counter:04d}",
        heading_path=heading_path,
        page_start=section.page_start,
        page_end=section.page_end,
        approx_tokens=approx_token_count(text),
        chunk_type=chunk_type_for_heading(" ".join(heading_path)),  # type: ignore[arg-type]
        key_terms=key_terms(text),
        text=text,
    )


def _iter_sections(
    sections: list[SectionBlock],
    parents: list[str],
) -> list[tuple[SectionBlock, list[str]]]:
    result: list[tuple[SectionBlock, list[str]]] = []
    for section in sections:
        path = [*parents, section.heading]
        result.append((section, path))
        result.extend(_iter_sections(section.subsections, path))
    return result
