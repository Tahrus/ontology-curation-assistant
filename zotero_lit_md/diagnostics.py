from __future__ import annotations

import re

from zotero_lit_md.schema import ClaimUnit, SectionBlock
from zotero_lit_md.text_cleaning import chunk_type_for_heading


def build_claim_units(sections: list[SectionBlock], *, paper_key: str, max_claims: int = 30) -> list[ClaimUnit]:
    claims: list[ClaimUnit] = []
    for section in _flatten_sections(sections):
        section_type = chunk_type_for_heading(section.heading)
        if section_type in {"reference", "declaration", "table", "figure_caption"}:
            continue
        for sentence in _sentences(section.text):
            if len(sentence.split()) < 8:
                continue
            if not _looks_like_claim(sentence):
                continue
            claims.append(
                ClaimUnit(
                    claim_id=f"{paper_key}_claim_{len(claims) + 1:04d}",
                    claim=sentence,
                    evidence_section=section.heading,
                    pages=_page_range(section.page_start, section.page_end),
                    type=section_type if section_type in {"method", "result", "conclusion"} else "background",
                )
            )
            if len(claims) >= max_claims:
                return claims
    return claims


def _flatten_sections(sections: list[SectionBlock]) -> list[SectionBlock]:
    flattened = []
    for section in sections:
        flattened.append(section)
        flattened.extend(_flatten_sections(section.subsections))
    return flattened


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]


def _looks_like_claim(sentence: str) -> bool:
    lowered = sentence.casefold()
    return any(
        cue in lowered
        for cue in [
            "we ",
            "results",
            "show",
            "demonstrate",
            "indicate",
            "suggest",
            "found",
            "measured",
            "method",
            "model",
            "limited",
        ]
    )


def _page_range(start: int | None, end: int | None) -> str:
    if start is None and end is None:
        return ""
    if start == end or end is None:
        return str(start)
    return f"{start}-{end}"
