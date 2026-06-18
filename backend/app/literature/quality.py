from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


METADATA_MATCH_STATUSES = {"matched", "weak_match", "metadata_mismatch", "unknown"}
DOI_MATCH_STATUSES = {"matched", "mismatch", "unknown"}
DOCUMENT_ROLES = {
    "domain_article",
    "methodology_article",
    "review_article",
    "supplementary_information",
    "unknown",
}
DEFAULT_LLM_EXTRACTION_ROLES = {"domain_article", "review_article"}
DOCUMENT_STATES = {
    "imported",
    "extracted",
    "extraction_failed",
    "validation_failed",
    "needs_review",
    "cleaned",
    "context_ready",
    "ready_for_llm",
    "blocked",
}
QUALITY_VERSION = "literature-quality-v1"


@dataclass(frozen=True)
class LiteratureQualityResult:
    metadata: dict[str, Any]
    clean_markdown: str
    llm_context_markdown: str
    report: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractorAvailability:
    grobid: bool
    docling: bool
    marker: bool
    pymupdf4llm: bool
    pymupdf: bool
    ocr: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "grobid": self.grobid,
            "docling": self.docling,
            "marker": self.marker,
            "pymupdf4llm": self.pymupdf4llm,
            "pymupdf": self.pymupdf,
            "ocr": self.ocr,
        }


def extractor_availability() -> ExtractorAvailability:
    """Return optional scientific-PDF extractor availability without importing heavy modules."""
    return ExtractorAvailability(
        grobid=bool(_has_executable("grobid_client") or _has_module("grobid_client")),
        docling=_has_module("docling"),
        marker=bool(_has_executable("marker_single") or _has_module("marker")),
        pymupdf4llm=_has_module("pymupdf4llm"),
        pymupdf=_has_module("fitz"),
        ocr=bool(_has_executable("tesseract") or _has_module("pytesseract")),
    )


def enrich_literature_markdown(
    paper: dict[str, Any],
    raw_markdown: str,
    *,
    base_dir: Path,
    canonical_path: Path | None = None,
) -> dict[str, Any]:
    """Create raw/clean/context/report artifacts and return front-matter fields."""
    base_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = base_dir / "raw"
    clean_dir = base_dir / "clean"
    context_dir = base_dir / "context"
    report_dir = base_dir / "reports"
    blocked_dir = base_dir / "blocked"
    for directory in [raw_dir, clean_dir, context_dir, report_dir, blocked_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    seed = str(paper.get("paper_id") or paper.get("id") or paper.get("doi") or paper.get("title") or "paper")
    slug = _artifact_slug(seed)
    raw_path = raw_dir / f"{slug}.md"
    clean_path = clean_dir / f"{slug}.md"
    context_path = context_dir / f"{slug}.md"
    report_path = report_dir / f"{slug}.json"

    # Raw extraction is trace evidence; keep the first copy byte-for-byte.
    if not raw_path.exists():
        raw_path.write_text(raw_markdown, encoding="utf-8")

    result = analyze_literature_markdown(paper, raw_markdown)
    clean_path.write_text(result.clean_markdown, encoding="utf-8")
    context_path.write_text(result.llm_context_markdown, encoding="utf-8")

    report = {
        **result.report,
        "canonical_markdown_file": str(canonical_path) if canonical_path else None,
        "raw_markdown_file": str(raw_path),
        "clean_markdown_file": str(clean_path),
        "llm_context_file": str(context_path),
        "metadata_report_file": str(report_path),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if result.metadata.get("state") in {"blocked", "needs_review", "validation_failed", "extraction_failed"}:
        marker = blocked_dir / f"{slug}.json"
        marker.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    return {
        **result.metadata,
        "raw_markdown_file": str(raw_path),
        "clean_markdown_file": str(clean_path),
        "llm_context_file": str(context_path),
        "metadata_report_file": str(report_path),
        "quality_version": QUALITY_VERSION,
    }


def analyze_literature_markdown(paper: dict[str, Any], raw_markdown: str) -> LiteratureQualityResult:
    """Validate metadata, classify document role, clean Markdown, and build LLM context."""
    metadata_title = str(paper.get("zotero_title") or paper.get("title") or "").strip()
    body = _strip_front_matter(raw_markdown)
    detected_title = detect_title(body, metadata_title=metadata_title)
    detected_doi = extract_doi(body)
    score = title_similarity(metadata_title, detected_title)
    status = metadata_match_status(metadata_title, detected_title, score)
    doi_status = doi_match_status(str(paper.get("zotero_doi") or paper.get("doi") or ""), detected_doi)
    cleanup = clean_markdown(raw_markdown, title=metadata_title or detected_title)
    role = classify_document_role(paper, cleanup["clean_markdown"], detected_title=detected_title)
    metrics = extraction_metrics(paper, raw_markdown, cleanup["clean_markdown"], detected_title=detected_title)

    warnings = list(cleanup["warnings"])
    requires_review = False
    exclude = False
    extraction_quality = str(paper.get("extraction_quality") or "usable")
    state = str(paper.get("state") or "extracted")
    if status == "metadata_mismatch":
        extraction_quality = "metadata_mismatch"
        requires_review = True
        exclude = True
        state = "blocked"
        warnings.append("Metadata title does not match detected extracted title.")
    elif doi_status == "mismatch":
        extraction_quality = "metadata_mismatch"
        requires_review = True
        exclude = True
        state = "blocked"
        warnings.append("Zotero DOI does not match detected DOI.")
    elif metrics["incomplete"]:
        extraction_quality = "incomplete"
        requires_review = True
        exclude = True
        state = "needs_review"
        warnings.extend(metrics["warnings"])
    elif status == "weak_match":
        requires_review = False
        state = "cleaned"

    if role == "methodology_article":
        exclude = True
    if role == "supplementary_information":
        exclude = True

    clean_exists = bool(cleanup["clean_markdown"].strip())
    context_placeholder_available = True
    if state not in {"blocked", "needs_review", "extraction_failed", "validation_failed"}:
        state = "context_ready" if clean_exists and context_placeholder_available else "cleaned"
    include = not exclude and not requires_review and role in DEFAULT_LLM_EXTRACTION_ROLES
    if include and state == "context_ready":
        state = "ready_for_llm"
    if not include and state == "ready_for_llm":
        state = "context_ready"

    now = datetime.now(timezone.utc).isoformat()
    pdf_path = str(paper.get("pdf_path") or paper.get("source_pdf") or "")
    pdf_sha = str(paper.get("pdf_sha256") or _sha256_file(pdf_path) or "")
    metadata = {
        "paper_id": paper.get("paper_id") or paper.get("id") or "",
        "zotero_key": paper.get("zotero_key") or "",
        "zotero_item_key": paper.get("zotero_item_key") or paper.get("zotero_key") or "",
        "pdf_path": pdf_path,
        "pdf_sha256": pdf_sha,
        "source_filename": paper.get("source_filename") or paper.get("source_file") or (Path(pdf_path).name if pdf_path else ""),
        "zotero_title": metadata_title,
        "zotero_authors": paper.get("zotero_authors") or paper.get("authors") or [],
        "zotero_year": paper.get("zotero_year") or paper.get("year"),
        "zotero_doi": paper.get("zotero_doi") or paper.get("doi") or "",
        "metadata_title": metadata_title,
        "detected_title": detected_title,
        "detected_authors": paper.get("detected_authors") or [],
        "detected_doi": detected_doi,
        "title_similarity_score": round(score, 3),
        "doi_match_status": doi_status,
        "metadata_match_status": status,
        "document_role": role,
        "extraction_quality": extraction_quality,
        "extraction_engine_used": paper.get("extraction_engine_used") or paper.get("extraction_method") or "canonical_markdown",
        "extraction_engine_attempts": paper.get("extraction_engine_attempts") or ["canonical_markdown"],
        "page_count_pdf": metrics["page_count_pdf"],
        "page_count_extracted": metrics["page_count_extracted"],
        "word_count": metrics["word_count"],
        "words_per_page": metrics["words_per_page"],
        "pages_with_text": metrics["pages_with_text"],
        "section_count": metrics["section_count"],
        "reference_count": metrics["reference_count"],
        "abstract_detected": metrics["abstract_detected"],
        "references_detected": metrics["references_detected"],
        "title_detected": bool(detected_title),
        "repeated_header_footer_score": metrics["repeated_header_footer_score"],
        "table_equation_artifact_score": metrics["table_equation_artifact_score"],
        "state": state,
        "requires_manual_review": requires_review,
        "exclude_from_llm_extraction": exclude,
        "exclude_from_automatic_llm_extraction": exclude,
        "include_in_llm_extraction": include,
        "cleanup_warnings": warnings,
        "warnings": sorted(set(warnings)),
        "created_at": paper.get("created_at") or now,
        "updated_at": now,
    }
    context = build_llm_context(
        paper,
        cleanup["clean_markdown"],
        metadata=metadata,
        warnings=warnings,
    )
    report = {
        "metadata": {
            "title": metadata_title,
            "authors": paper.get("authors") or [],
            "year": paper.get("year"),
            "doi": paper.get("doi") or "",
            "source_filename": paper.get("source_file") or paper.get("source_pdf") or "",
            "zotero_key": paper.get("zotero_key") or paper.get("paper_id") or paper.get("id") or "",
        },
        "validation": metadata,
        "quality_metrics": metrics,
        "cleanup": {
            "status": "cleaned_with_warnings" if warnings else "cleaned",
            "rule_counts": cleanup["rule_counts"],
            "warnings": warnings,
        },
        "document_role": role,
    }
    return LiteratureQualityResult(metadata=metadata, clean_markdown=cleanup["clean_markdown"], llm_context_markdown=context, report=report, warnings=warnings)


def detect_title(markdown_body: str, *, metadata_title: str = "") -> str:
    """Conservatively detect apparent paper title from early extracted Markdown."""
    lines = [line.strip(" #\t") for line in markdown_body.splitlines()[:120]]
    blacklist = {
        "abstract",
        "introduction",
        "summary",
        "keywords",
        "references",
        "llm-ready full-text markdown",
        "minimal metadata",
    }
    skipped_metadata_title = False
    capture_next_title_line = False
    metadata_norm = _normalize_title(metadata_title)
    for line in lines:
        if not line:
            continue
        normalized = _normalize_title(line)
        if normalized in blacklist:
            continue
        if normalized in {"title", "front matter", "full text"}:
            capture_next_title_line = True
            continue
        if normalized in {
            "notes",
            "extracted ontology relevant information",
            "introduction",
            "background",
            "methods",
            "results",
            "discussion",
            "conclusion",
            "conclusions",
        }:
            capture_next_title_line = False
            continue
        if line.startswith("<!--"):
            continue
        if metadata_norm and _normalize_title(line) == metadata_norm and not skipped_metadata_title:
            skipped_metadata_title = True
            continue
        if re.search(r"\b(?:doi|copyright|downloaded|all rights reserved|images omitted)\b", line, re.I):
            continue
        words = line.split()
        if capture_next_title_line and 4 <= len(words) <= 24 and sum(char.isalpha() for char in line) >= 20:
            return line.rstrip(".")
    return ""


def title_similarity(left: str, right: str) -> float:
    left_norm = _normalize_title(left)
    right_norm = _normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def metadata_match_status(metadata_title: str, detected_title: str, score: float) -> str:
    if not metadata_title or not detected_title:
        return "unknown"
    if re.search(r"\.(?:txt|md|pdf|docx?)$", metadata_title, re.I):
        return "unknown"
    if score >= 0.84:
        return "matched"
    if score >= 0.68:
        return "weak_match"
    return "metadata_mismatch"


def doi_match_status(zotero_doi: str, detected_doi: str) -> str:
    left = _normalize_doi(zotero_doi)
    right = _normalize_doi(detected_doi)
    if not left or not right:
        return "unknown"
    return "matched" if left == right else "mismatch"


def extract_doi(text: str) -> str:
    match = re.search(r"\b10\.\d{4,9}/[^\s,;\"<>]+", text, re.I)
    return match.group(0).rstrip(".).,;") if match else ""


def extraction_metrics(
    paper: dict[str, Any],
    raw_markdown: str,
    clean: str,
    *,
    detected_title: str = "",
) -> dict[str, Any]:
    body = _strip_front_matter(raw_markdown)
    clean_body = _strip_front_matter(clean)
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9-]*\b", clean_body)
    word_count = len(words)
    page_count_pdf = _int_or_zero(paper.get("page_count_pdf") or paper.get("page_count"))
    page_markers = re.findall(r"source_page\s*[:=]\s*(\d+)", raw_markdown, re.I)
    page_count_extracted = len(set(page_markers)) if page_markers else (1 if word_count else 0)
    pages_with_text = page_count_extracted if word_count else 0
    denominator = page_count_pdf or page_count_extracted or 1
    words_per_page = round(word_count / denominator, 1)
    sections = re.findall(r"(?m)^#{2,4}\s+(.+)$", clean_body)
    references = re.findall(r"(?im)^#{2,4}\s+(references|bibliography|literature cited)\s*$", clean_body)
    abstract_detected = bool(re.search(r"(?im)^#{2,4}\s+abstract\s*$", clean_body)) or bool(paper.get("abstract"))
    repeated_lines = _repeated_lines(body.splitlines())
    table_equation_blocks = len(re.findall(r"```(?:math|text)", clean_body)) + clean_body.count("table requires manual review")
    warnings: list[str] = []
    if page_count_pdf and word_count < max(120, page_count_pdf * 80):
        warnings.append("Extracted word count is too low for the PDF page count.")
    if page_count_pdf and pages_with_text and pages_with_text < max(1, page_count_pdf // 2):
        warnings.append("Many PDF pages appear to have no extracted text.")
    if not detected_title and page_count_pdf:
        warnings.append("No reliable extracted title was detected.")
    if not sections and word_count > 80:
        warnings.append("No meaningful section headings were detected.")
    if page_count_pdf and _looks_like_fragment_only(clean_body):
        warnings.append("Extracted body appears to contain only fragments, captions, references, or metadata.")
    incomplete = bool(warnings)
    return {
        "page_count_pdf": page_count_pdf,
        "page_count_extracted": page_count_extracted,
        "word_count": word_count,
        "words_per_page": words_per_page,
        "pages_with_text": pages_with_text,
        "section_count": len([s for s in sections if s.casefold() not in {"references", "bibliography"}]),
        "reference_count": len(references),
        "abstract_detected": abstract_detected,
        "references_detected": bool(references),
        "repeated_header_footer_score": round(min(1.0, len(repeated_lines) / 10), 2),
        "table_equation_artifact_score": round(min(1.0, table_equation_blocks / 10), 2),
        "incomplete": incomplete,
        "warnings": warnings,
    }


def classify_document_role(paper: dict[str, Any], markdown_body: str, *, detected_title: str = "") -> str:
    body = _strip_front_matter(markdown_body)
    text = " ".join(
        str(part or "")
        for part in [
            paper.get("title"),
            detected_title,
            paper.get("abstract"),
            " ".join(_early_lines(body, 160)),
        ]
    ).casefold()
    if re.search(r"\bsupplement(?:ary|al)|supporting information|appendix\b", text):
        return "supplementary_information"
    if re.search(r"\bsystematic review|literature review|review article|review of|meta-analysis|survey\b", text):
        return "review_article"
    methodology_terms = [
        "ontology engineering",
        "knowledge graph",
        "large language model",
        "llm",
        "prompt",
        "entity disambiguation",
        "ontology alignment",
        "workflow architecture",
        "evaluation framework",
    ]
    if any(term in text for term in methodology_terms):
        return "methodology_article"
    domain_terms = [
        "protein",
        "precipitation",
        "crystallization",
        "aggregation",
        "nucleation",
        "growth",
        "population balance",
        "solvent",
        "bioprocess",
        "particle",
    ]
    if any(term in text for term in domain_terms):
        return "domain_article"
    if len(text.strip()) >= 40:
        return "domain_article"
    return "unknown"


def clean_markdown(raw_markdown: str, *, title: str = "") -> dict[str, Any]:
    metadata, body = _split_front_matter(raw_markdown)
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}
    seen_title = False
    repeated = _repeated_lines(lines)
    table_buffer: list[str] = []
    equation_buffer: list[str] = []

    def count(rule: str) -> None:
        counts[rule] = counts.get(rule, 0) + 1

    def flush_table() -> None:
        nonlocal table_buffer
        if not table_buffer:
            return
        kept.append("<!-- table requires manual review -->")
        kept.append("```text")
        kept.extend(table_buffer)
        kept.append("```")
        warnings.append("A table-like block was isolated for manual review.")
        count("table_manual_review")
        table_buffer = []

    def flush_equation() -> None:
        nonlocal equation_buffer
        if not equation_buffer:
            return
        kept.append("```math")
        kept.extend(equation_buffer)
        kept.append("```")
        warnings.append("Equation-like fragments were isolated.")
        count("equation_isolated")
        equation_buffer = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_table()
            flush_equation()
            kept.append("")
            continue
        boilerplate = _boilerplate_rule(line)
        if boilerplate:
            count(boilerplate)
            continue
        if line.startswith("<!--") and "source_page" in line:
            count("source_page_comment")
            continue
        if line in repeated and len(line) < 140:
            count("repeated_header_footer")
            continue
        normalized = _normalize_title(line.lstrip("# "))
        if title and normalized == _normalize_title(title):
            if seen_title:
                count("duplicate_title")
                continue
            seen_title = True
            kept.append(f"# {title}")
            continue
        if _looks_like_table_line(line):
            flush_equation()
            table_buffer.append(line)
            continue
        if _looks_like_equation_fragment(line):
            flush_table()
            equation_buffer.append(line)
            continue
        flush_table()
        flush_equation()
        heading = _normalize_heading_line(line)
        if heading:
            kept.append(heading)
        elif re.match(r"^(figure|fig\.|table)\s+\d+", line, re.I):
            kept.append(f"> **Caption:** {line}")
        else:
            kept.append(line)
    flush_table()
    flush_equation()
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"(\w)-\n(\w)", r"\1\2", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    references = re.split(r"(?im)^#{1,4}\s*references\s*$", cleaned, maxsplit=1)
    if len(references) == 2:
        cleaned = f"{references[0].rstrip()}\n\n## References\n\n{references[1].strip()}"
    front = _front_matter(metadata) if metadata else ""
    return {
        "clean_markdown": f"{front}\n\n{cleaned}\n" if front else f"{cleaned}\n",
        "warnings": sorted(set(warnings)),
        "rule_counts": counts,
    }


def build_llm_context(
    paper: dict[str, Any],
    clean_markdown: str,
    *,
    metadata: dict[str, Any],
    warnings: list[str],
) -> str:
    role = metadata.get("document_role") or "unknown"
    body = _strip_front_matter(clean_markdown)
    snippets = _evidence_snippets(body)
    bibliography = [
        f"- Title: {paper.get('title') or metadata.get('metadata_title') or 'Untitled'}",
        f"- Detected title: {metadata.get('detected_title') or 'unknown'}",
        f"- Authors: {', '.join(str(a) for a in paper.get('authors') or []) or 'unknown'}",
        f"- Year: {paper.get('year') or 'unknown'}",
        f"- DOI: {paper.get('doi') or 'unknown'}",
        f"- Metadata match: {metadata.get('metadata_match_status')} ({metadata.get('title_similarity_score')})",
        f"- Document role: {role}",
    ]
    sections_by_role = {
        "domain_article": [
            "Abstract or detected summary",
            "Curation-relevant concepts",
            "Candidate processes",
            "Candidate material entities",
            "Candidate qualities/parameters",
            "Candidate measurements/data items",
            "Candidate relations",
            "Evidence snippets with page anchors",
            "Warnings and limitations",
        ],
        "methodology_article": [
            "Main methodological claim",
            "Relevant methods",
            "Workflow recommendations",
            "Evaluation ideas",
            "Prompting or LLM-use recommendations",
            "Relevance for OCA architecture",
            "Concepts that are methodology/tool concepts, not target-domain ontology concepts",
        ],
        "review_article": [
            "Review scope",
            "Important terminology",
            "Domain overview",
            "Candidate ontology areas",
            "Relevant references or subtopics",
            "Warnings about broad/general claims",
        ],
        "supplementary_information": [
            "Parent article if detected",
            "Technical details",
            "Methods",
            "Additional results",
            "Tables/figures requiring review",
            "Relevance to parent article",
            "Extraction warnings",
        ],
        "unknown": [
            "Review-needed summary",
            "Potentially relevant text",
            "Warnings and limitations",
        ],
    }
    blocks = ["# LLM Context", "", "## Bibliographic metadata", "", *bibliography, ""]
    for heading in sections_by_role.get(role, sections_by_role["unknown"]):
        blocks.extend([f"## {heading}", ""])
        if heading in {"Abstract or detected summary", "Main methodological claim", "Review scope", "Review-needed summary"}:
            blocks.append(_first_meaningful_paragraph(body) or "No reliable summary detected.")
        elif heading == "Evidence snippets with page anchors":
            blocks.extend(snippets or ["No evidence snippets detected."])
        elif "Warnings" in heading or heading == "Extraction warnings":
            blocks.extend([f"- {warning}" for warning in warnings] or ["- No cleanup warnings."])
        elif "methodology/tool concepts" in heading:
            blocks.append("Methodology/tool concepts in this document must not be treated as target-domain ontology classes unless the active project explicitly models ontology engineering.")
        else:
            blocks.append(_keyword_lines(body, heading))
        blocks.append("")
    blocks.extend([
        "## Concept boundary note",
        "",
        "Distinguish target-domain ontology concepts from methodology/tool concepts, bibliographic/reference concepts, and noisy extraction artifacts.",
    ])
    return "\n".join(blocks).strip() + "\n"


def should_include_for_automatic_llm(paper: dict[str, Any], *, task: str = "domain_ontology_extraction") -> tuple[bool, str]:
    status = str(paper.get("metadata_match_status") or paper.get("metadata", {}).get("metadata_match_status") or "unknown")
    role = str(paper.get("document_role") or paper.get("metadata", {}).get("document_role") or "unknown")
    quality = str(paper.get("extraction_quality") or paper.get("metadata", {}).get("extraction_quality") or "unknown")
    state = str(paper.get("state") or paper.get("metadata", {}).get("state") or "unknown")
    requires_review = _as_bool(paper.get("requires_manual_review") or paper.get("metadata", {}).get("requires_manual_review"))
    excluded = _as_bool(paper.get("exclude_from_automatic_llm_extraction") or paper.get("metadata", {}).get("exclude_from_automatic_llm_extraction"))
    included = _as_bool(paper.get("include_in_llm_extraction"), default=True)
    clean_markdown = paper.get("clean_markdown") or paper.get("clean_markdown_file") or paper.get("metadata", {}).get("clean_markdown_file")
    context_markdown = paper.get("llm_context_markdown") or paper.get("llm_context_file") or paper.get("metadata", {}).get("llm_context_file")
    if status == "metadata_mismatch" or quality == "metadata_mismatch":
        return False, "metadata_mismatch"
    if quality in {"incomplete", "failed", "extraction_failed"}:
        return False, f"extraction_quality={quality}"
    if requires_review:
        return False, "requires_manual_review"
    if not clean_markdown:
        return False, "missing_clean_markdown"
    if not context_markdown:
        return False, "missing_llm_context"
    if excluded or not included:
        return False, "user_or_role_excluded"
    if task == "domain_ontology_extraction" and role not in DEFAULT_LLM_EXTRACTION_ROLES:
        return False, f"unsuitable_document_role={role}"
    if state and state not in {"ready_for_llm", "unknown"}:
        return False, f"document_state={state}"
    return True, "included"


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _has_executable(name: str) -> bool:
    return shutil.which(name) is not None


def _sha256_file(path_value: str) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _normalize_doi(value: str) -> str:
    return re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", str(value or "").strip().casefold()).rstrip(".")


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _looks_like_fragment_only(text: str) -> bool:
    body = _strip_front_matter(text)
    prose = [
        line.strip()
        for line in body.splitlines()
        if line.strip()
        and not line.startswith("#")
        and not line.startswith("<!--")
        and not re.match(r"^(figure|fig\.|table|references?)\b", line.strip(), re.I)
    ]
    if not prose:
        return True
    long_prose = [line for line in prose if len(line.split()) >= 8]
    return len(long_prose) == 0 and len(" ".join(prose).split()) < 80


def _artifact_slug(seed: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", seed).strip("-").lower()[:80] or "paper"
    digest = hashlib.sha1(seed.casefold().encode("utf-8")).hexdigest()[:8]
    return f"{normalized}-{digest}"


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    front = text[4:end].strip("\n")
    body = text[end + len("\n---"):].lstrip("\n")
    return _parse_front_matter(front), body


def _strip_front_matter(text: str) -> str:
    return _split_front_matter(text)[1]


def _parse_front_matter(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if current and line.startswith("  - "):
            result[current].append(_unquote(line[4:]))
            continue
        current = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if value.strip():
            result[key.strip()] = _unquote(value.strip())
        else:
            result[key.strip()] = []
            current = key.strip()
    return result


def _front_matter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_quote(item)}")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {_quote(value)}")
    lines.append("---")
    return "\n".join(lines)


def _quote(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(value: str) -> Any:
    text = value.strip()
    if text in {"true", "false"}:
        return text == "true"
    if text == "null":
        return None
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text) if "." in text else int(text)
    return text


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _early_lines(text: str, count: int) -> list[str]:
    return [line.strip() for line in text.splitlines()[:count] if line.strip()]


def _repeated_lines(lines: list[str]) -> set[str]:
    stripped = [line.strip() for line in lines if line.strip()]
    return {line for line in stripped if stripped.count(line) >= 3}


def _boilerplate_rule(line: str) -> str | None:
    patterns = {
        "generated_boilerplate": r"llm-ready full-text markdown|this markdown file was generated from a pdf|minimal metadata|images omitted",
        "publisher_boilerplate": r"downloaded from|view article online|journal navigation|all rights reserved|copyright|\b(?:elsevier|springer|wiley|acs publications|mdpi)\b",
        "license_notice": r"creative commons|open access article|licensee mdpi|published by",
        "page_number": r"^(?:page\s*)?\d+$",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, line, re.I):
            return name
    return None


def _looks_like_table_line(line: str) -> bool:
    return line.count("|") >= 2 or bool(re.search(r"\s{2,}\S+\s{2,}\S+", line)) and len(line.split()) >= 4


def _looks_like_equation_fragment(line: str) -> bool:
    return bool(re.search(r"[=∑∫√≤≥±]|\\(?:frac|sum|alpha|beta|gamma)", line)) and len(line) < 180


def _normalize_heading_line(line: str) -> str | None:
    if line.startswith("#"):
        marker, _, heading = line.partition(" ")
        if heading:
            return f"{marker[:3]} {heading.strip()}"
    canonical = {
        "abstract",
        "summary",
        "introduction",
        "background",
        "methods",
        "methodology",
        "materials and methods",
        "results",
        "discussion",
        "conclusion",
        "conclusions",
        "references",
    }
    clean = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", line).strip()
    if clean.casefold() in canonical:
        return f"## {clean.title() if clean.casefold() != 'references' else 'References'}"
    return None


def _evidence_snippets(text: str) -> list[str]:
    snippets = []
    for index, paragraph in enumerate(re.split(r"\n\s*\n", text), start=1):
        clean = re.sub(r"\s+", " ", paragraph).strip()
        if len(clean) >= 80 and not clean.startswith("#"):
            snippets.append(f"- [p? paragraph-{index}] {clean[:450]}")
        if len(snippets) >= 5:
            break
    return snippets


def _first_meaningful_paragraph(text: str) -> str:
    for paragraph in re.split(r"\n\s*\n", text):
        clean = _clean_context_paragraph(paragraph)
        if len(clean) >= 20:
            return clean[:900]
    return ""


def _keyword_lines(text: str, heading: str) -> str:
    keywords = {
        "processes": ["process", "nucleation", "growth", "aggregation", "precipitation", "crystallization"],
        "material": ["protein", "particle", "solvent", "crystal", "aggregate"],
        "qualities": ["rate", "size", "concentration", "temperature", "ph", "parameter"],
        "measurements": ["measurement", "data", "distribution", "kinetic", "model"],
        "relations": ["causes", "depends", "increases", "decreases", "input", "output"],
        "methods": ["method", "workflow", "pipeline", "architecture", "prompt", "evaluation"],
    }
    selected = []
    normalized_heading = heading.casefold()
    active_terms = [term for label, terms in keywords.items() if label in normalized_heading for term in terms]
    for paragraph in re.split(r"\n\s*\n", text):
        clean = _clean_context_paragraph(paragraph)
        if active_terms and any(term in clean.casefold() for term in active_terms):
            selected.append(f"- {clean[:350]}")
        if len(selected) >= 4:
            break
    if selected:
        return "\n".join(selected)
    fallback = _first_meaningful_paragraph(text)
    return f"- {fallback[:350]}" if fallback else "No deterministic candidates detected; curator review recommended."


def _clean_context_paragraph(paragraph: str) -> str:
    skipped = {
        "abstract",
        "notes",
        "extracted ontology-relevant information",
        "references",
    }
    lines = []
    for raw_line in paragraph.splitlines():
        line = raw_line.strip()
        normalized = re.sub(r"[^a-z0-9]+", " ", line.lstrip("# ")).strip()
        if not line or normalized.casefold() in skipped:
            continue
        if line.startswith("<!--"):
            continue
        if re.fullmatch(r"#{1,6}\s+.+", line):
            continue
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip(" #")


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}
