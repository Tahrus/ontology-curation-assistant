#!/usr/bin/env python3
"""Convert scientific PDFs into conservative, structured Markdown.

This is a best-effort extractor for ontology/LLM input. It does not summarize
or rewrite scientific content. Its goal is to remove obvious PDF/article
plumbing, repair common extraction artifacts, preserve the body text, and mark
uncertain tables/equations instead of inventing content.

Usage:
    python scripts/pdf_to_clean_markdown.py paper.pdf -o paper.md
    python scripts/pdf_to_clean_markdown.py paper.pdf --debug
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import signal
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

try:
    import fitz  # PyMuPDF
except Exception as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: PyMuPDF. Install with: pip install pymupdf") from exc

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None


BACK_MATTER_HEADINGS = {
    "references",
    "bibliography",
    "acknowledgements",
    "acknowledgments",
    "funding",
    "author contributions",
    "credit authorship contribution statement",
    "declaration of competing interest",
    "conflict of interest",
    "conflicts of interest",
    "data availability",
    "ethics approval",
    "supplementary material",
}

FRONT_MATTER_PATTERNS = [
    r"^article history$",
    r"^received\b",
    r"^accepted\b",
    r"^available online\b",
    r"^corresponding author\b",
    r"^e-?mail\b",
    r"^doi\b",
    r"^https?://",
    r"^contents lists available",
    r"^journal homepage",
    r"^copyright\b",
    r"^©",
    r"^research article\b",
    r"^peer reviewed",
]

SECTION_WORDS = {
    "abstract",
    "keywords",
    "introduction",
    "background",
    "materials and methods",
    "methods",
    "methodology",
    "experimental",
    "theory",
    "system description",
    "results",
    "results and discussion",
    "discussion",
    "conclusion",
    "conclusions",
}

LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}

PUNCTUATION = {
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a0": " ",
}


@dataclasses.dataclass
class PageText:
    page: int
    lines: list[str]


@dataclasses.dataclass
class ExtractedTable:
    page: int
    index: int
    rows: list[list[str]]

    @property
    def markdown(self) -> str:
        rows = [[clean_cell(cell) for cell in row] for row in self.rows if any(clean_cell(c) for c in row)]
        if len(rows) < 2:
            return ""
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        header = padded[0]
        body = padded[1:]
        out = []
        out.append("| " + " | ".join(escape_pipe(c) for c in header) + " |")
        out.append("| " + " | ".join("---" for _ in header) + " |")
        for row in body:
            out.append("| " + " | ".join(escape_pipe(c) for c in row) + " |")
        return "\n".join(out)


def normalize_text(text: str) -> str:
    for src, dst in LIGATURES.items():
        text = text.replace(src, dst)
    for src, dst in PUNCTUATION.items():
        text = text.replace(src, dst)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_cell(value: object) -> str:
    return normalize_text("" if value is None else str(value)).replace("\n", " ")


def escape_pipe(value: str) -> str:
    return value.replace("|", r"\|")


def slugify(path: Path) -> str:
    stem = re.sub(r"\.pdf$", "", path.name, flags=re.I)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_")
    return stem or "paper"


def extract_pages_with_poppler(pdf_path: Path) -> list[PageText] | None:
    try:
        info = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    m = re.search(r"^Pages:\s+(\d+)", info.stdout, flags=re.M)
    if not m:
        return None
    page_count = int(m.group(1))
    pages: list[PageText] = []
    for page_number in range(1, page_count + 1):
        try:
            result = subprocess.run(
                ["pdftotext", "-q", "-f", str(page_number), "-l", str(page_number), str(pdf_path), "-"],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None
        lines = [normalize_text(line) for line in result.stdout.splitlines()]
        pages.append(PageText(page_number, [line for line in lines if line]))
    return pages


def extract_pages_with_pymupdf(pdf_path: Path) -> list[PageText]:
    doc = fitz.open(pdf_path)
    pages: list[PageText] = []
    for page_index, page in enumerate(doc, start=1):
        blocks = page.get_text("blocks", sort=True)
        lines: list[str] = []
        for block in blocks:
            if len(block) < 5:
                continue
            text = normalize_text(block[4])
            if not text:
                continue
            for line in text.splitlines():
                line = normalize_text(line)
                if line:
                    lines.append(line)
        pages.append(PageText(page_index, lines))
    return pages


def extract_pages(pdf_path: Path) -> list[PageText]:
    return extract_pages_with_poppler(pdf_path) or extract_pages_with_pymupdf(pdf_path)


class Timeout:
    def __init__(self, seconds: int):
        self.seconds = seconds
        self._enabled = self.seconds > 0 and hasattr(signal, "SIGALRM")

    def __enter__(self) -> None:
        if not self._enabled:
            return
        signal.signal(signal.SIGALRM, self._raise_timeout)
        signal.alarm(self.seconds)

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._enabled:
            signal.alarm(0)
        return False

    @staticmethod
    def _raise_timeout(signum, frame) -> None:  # pragma: no cover
        raise TimeoutError("table extraction timed out")


def extract_tables(pdf_path: Path, per_page_timeout: int = 5) -> tuple[list[ExtractedTable], list[str]]:
    if pdfplumber is None:
        return [], ["pdfplumber is not installed; table extraction skipped."]
    tables: list[ExtractedTable] = []
    warnings: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            try:
                with Timeout(per_page_timeout):
                    page_tables = page.extract_tables() or []
            except TimeoutError:
                warnings.append(f"Table extraction timed out on page {page_index}; page skipped.")
                continue
            except Exception:
                warnings.append(f"Table extraction failed on page {page_index}; page skipped.")
                continue
            for table_index, rows in enumerate(page_tables, start=1):
                if not rows:
                    continue
                non_empty = sum(1 for row in rows for cell in row if clean_cell(cell))
                if non_empty >= 6:
                    tables.append(ExtractedTable(page_index, table_index, rows))
    return tables, warnings


def is_page_number(line: str) -> bool:
    return bool(re.fullmatch(r"\d{1,5}", line))


def is_probable_running_line(line: str, page_count: int) -> bool:
    low = line.lower().strip()
    if is_page_number(line):
        return True
    if "downloaded from" in low or "all rights reserved" in low:
        return True
    if re.search(r"\b\d{4}\s*[-:]\s*\d{1,5}\b", low) and ("journal" in low or "trans" in low):
        return True
    if " / " in line and re.search(r"\b\d+\s*\(\d{4}\)\s*\d+", line):
        return True
    if page_count > 2 and (low.startswith("http://") or low.startswith("https://")):
        return True
    return False


def remove_running_headers(pages: list[PageText]) -> tuple[list[str], list[str]]:
    page_count = len(pages)
    line_pages: defaultdict[str, set[int]] = defaultdict(set)
    for page in pages:
        for line in page.lines:
            key = re.sub(r"\d+", "#", line.lower()).strip()
            if key:
                line_pages[key].add(page.page)

    repeated = {
        key for key, seen in line_pages.items()
        if page_count >= 4 and len(seen) >= max(2, page_count // 3)
    }

    removed: list[str] = []
    kept: list[str] = []
    for page in pages:
        for line in page.lines:
            key = re.sub(r"\d+", "#", line.lower()).strip()
            if key in repeated or is_probable_running_line(line, page_count):
                removed.append(line)
            else:
                kept.append(line)
    return kept, removed


def looks_like_front_matter(line: str) -> bool:
    low = line.lower().strip(": ")
    return any(re.search(pattern, low) for pattern in FRONT_MATTER_PATTERNS)


def find_back_matter_start(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        low = re.sub(r"^\d+(\.\d+)*\.?\s+", "", line.lower()).strip(" .:")
        if low in BACK_MATTER_HEADINGS:
            tail = "\n".join(lines[i + 1:i + 80]).lower()
            if low in {"references", "bibliography"} and re.search(
                r"(^|\n)\s*\d+(\.\d+)*\.?\s+(conclusion|conclusions|discussion|results)\b",
                tail,
            ):
                continue
            return i
    return len(lines)


def is_reference_heading(line: str) -> bool:
    low = re.sub(r"^\d+(\.\d+)*\.?\s+", "", line.lower()).strip(" .:")
    return low in {"references", "bibliography"}


def is_reference_line(line: str) -> bool:
    stripped = line.strip()
    return bool(
        re.match(r"^\d+\.\s+[A-Z][A-Za-z-]+,\s+[A-Z]", stripped)
        or re.match(r"^[A-Z][A-Za-z-]+,\s+[A-Z]", stripped)
        or re.match(r"^[A-Z][A-Za-z-]+,\s+[A-Z].*\(\d{4}\)", stripped)
        or re.search(r"\b(journal|engineering|elsevier|springer|wiley|doi|https?://)\b", stripped, re.I)
    )


def detect_title(lines: list[str], pdf_path: Path) -> str:
    try:
        meta_title = normalize_text(fitz.open(pdf_path).metadata.get("title") or "")
    except Exception:
        meta_title = ""
    if meta_title and not meta_title.lower().endswith((".docx", ".pdf")) and len(meta_title) > 8:
        return meta_title

    before_abstract: list[str] = []
    for line in lines[:80]:
        if line.lower().strip() == "abstract":
            break
        if re.search(r"\b(escape|symposium|conference|proceeding|ghent|editor)\b|\(eds?\.\)", line, re.I):
            continue
        if looks_like_front_matter(line):
            continue
        if line.count(",") >= 2 or ("*" in line and ",") or re.search(r"\b[A-Z][a-z]+[a-z]\s*,\s+[A-Z][a-z]+", line):
            continue
        if re.search(r"@|\bdepartment\b|\buniversity\b|\binstitute\b|\bed\.", line, re.I):
            continue
        if len(line.split()) <= 2 and not re.search(r"[a-z]", line):
            continue
        before_abstract.append(line)

    candidates: list[str] = []
    for line in before_abstract:
        if candidates and line.count(",") >= 1:
            break
        if len(line) >= 12 and not re.search(r"\d{4}", line):
            candidates.append(line)
        elif candidates:
            break
        if len(" ".join(candidates)) > 160:
            break
    title = " ".join(candidates[:3]).strip()
    return title or pdf_path.stem


def should_skip_line(line: str, in_body: bool) -> bool:
    if re.search(r"\b(escape|symposium|conference proceeding|pse press|licensed to|creative commons|ghent|eds?\.)\b", line, re.I):
        return True
    if looks_like_front_matter(line):
        return True
    if not in_body and re.search(r"@|\bcorresponding author\b|\bdepartment\b|\buniversity\b|\binstitute\b", line, re.I):
        return True
    return False


def is_caption(line: str) -> bool:
    return bool(re.match(r"^(fig\.?|figure|table)\s*\d+[.:]?\s+", line.strip(), re.I))


def is_heading(line: str) -> bool:
    stripped = line.strip()
    low = stripped.lower().strip(":")
    if low in SECTION_WORDS:
        return True
    if re.match(r"^\d+(\.\d+)*\.?\s+[A-Z][A-Za-z0-9 ,:/()&-]{2,}$", stripped):
        if is_reference_line(stripped):
            return False
        return True
    if len(stripped) <= 90 and stripped.isupper() and any(c.isalpha() for c in stripped):
        if "," in stripped or len(stripped.split()) < 2:
            return False
        return True
    return False


def heading_level(line: str) -> int:
    stripped = line.strip()
    if stripped.lower().strip(":") == "abstract":
        return 2
    m = re.match(r"^(\d+(?:\.\d+)*)\.?\s+", stripped)
    if not m:
        return 2
    depth = m.group(1).count(".") + 2
    return min(depth, 5)


def markdown_heading(line: str) -> str:
    level = heading_level(line)
    text = re.sub(r"\s+", " ", line.strip()).strip(".")
    return "#" * level + " " + title_case_section(text)


def title_case_section(text: str) -> str:
    # Preserve numbered headings, but normalize all-caps labels.
    if text.isupper():
        return text.title()
    return text


def abstract_inline_text(line: str) -> str | None:
    stripped = line.strip()
    if re.fullmatch(r"abstract[:.]?", stripped, flags=re.I):
        return ""
    match = re.match(r"^abstract[:.]?\s+(.+)$", stripped, flags=re.I)
    if match:
        return match.group(1).strip()
    return None


def normalized_section_label(line: str) -> str:
    label = re.sub(r"^\d+(\.\d+)*\.?\s+", "", line.lower()).strip(" .:")
    return re.sub(r"\s+", " ", label)


def find_body_start_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if abstract_inline_text(line) is not None:
            return index

    preferred_starts = {
        "introduction",
        "background",
        "materials and methods",
        "methods",
        "methodology",
        "experimental",
    }
    for index, line in enumerate(lines):
        label = normalized_section_label(line)
        if label in preferred_starts or label.startswith("introduction "):
            return index

    for index, line in enumerate(lines):
        if is_heading(line) and not looks_like_front_matter(line) and not is_reference_heading(line):
            return index

    return 0


def join_paragraph_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        line = normalize_text(line)
        if not text:
            text = line
            continue
        if text.endswith("-") and line and line[0].islower():
            text = text[:-1] + line
        else:
            text += " " + line
    text = re.sub(r"\s+", " ", text).strip()
    return text


def table_number(caption: str) -> str | None:
    m = re.search(r"\btable\s*(\d+)", caption, re.I)
    return m.group(1) if m else None


def group_lines_to_markdown(lines: list[str], title: str, tables: list[ExtractedTable]) -> tuple[str, dict]:
    stats = {
        "removed_back_matter_lines": 0,
        "approximate_tables": len(tables),
        "unclear_equation_markers": 0,
    }

    out: list[str] = [f"# {title}", ""]
    para: list[str] = []
    in_body = False
    seen_abstract = False
    body_start_index = find_body_start_index(lines)
    body_started = False
    used_tables: set[tuple[int, int]] = set()
    skipping_references = False
    seen_references = False

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append(join_paragraph_lines(para))
            out.append("")
            para = []

    for index, line in enumerate(lines):
        line = normalize_text(line)
        if not line:
            continue
        if is_reference_heading(line):
            flush_para()
            skipping_references = True
            seen_references = True
            stats["removed_back_matter_lines"] += 1
            continue
        abstract_text = abstract_inline_text(line)
        if not body_started and index < body_start_index:
            # Title/authors/affiliations/conference metadata are represented by
            # the H1 title. The body starts at the abstract in most articles,
            # with a fallback to the first plausible major section.
            continue
        body_started = True
        if not seen_abstract and abstract_text is not None:
            seen_abstract = True
            flush_para()
            out.append("## Abstract")
            out.append("")
            if abstract_text:
                para.append(abstract_text)
            in_body = True
            continue
        if skipping_references:
            if is_heading(line) and not is_reference_line(line):
                skipping_references = False
            else:
                stats["removed_back_matter_lines"] += 1
                continue
        if seen_references and (
            re.match(r"^\d+\.?$", line)
            or is_reference_line(line)
            or re.search(r"\b(licensed|creative commons|adaptations|authors\.|psecommunity)\b", line, re.I)
        ):
            stats["removed_back_matter_lines"] += 1
            continue
        if is_reference_line(line) and re.search(r"\(\d{4}\)|\b\d{4}\.", line):
            stats["removed_back_matter_lines"] += 1
            continue
        if should_skip_line(line, in_body):
            continue
        if line == title or line in title:
            continue
        low = line.lower().strip(":")
        if low == "keywords":
            flush_para()
            out.append("**Keywords:**")
            in_body = True
            continue
        if line.lower().startswith("keywords:"):
            flush_para()
            out.append("**" + line[:9] + "**" + line[9:])
            out.append("")
            in_body = True
            continue
        if is_heading(line):
            flush_para()
            out.append(markdown_heading(line))
            out.append("")
            in_body = True
            continue
        if is_caption(line):
            flush_para()
            out.append("**" + line + "**")
            out.append("")
            num = table_number(line)
            if num:
                for table in tables:
                    key = (table.page, table.index)
                    if key not in used_tables and table.markdown:
                        out.append("[table formatting approximate]")
                        out.append("")
                        out.append(table.markdown)
                        out.append("")
                        used_tables.add(key)
                        break
            in_body = True
            continue
        if re.search(r"([=∑∫√]|\\frac|\\sum|\\int)", line) and len(line) < 220:
            flush_para()
            out.append(line if not has_garbled_math(line) else "[equation extraction unclear]")
            if has_garbled_math(line):
                stats["unclear_equation_markers"] += 1
            out.append("")
            continue
        para.append(line)

    flush_para()

    unused = [t for t in tables if (t.page, t.index) not in used_tables and t.markdown]
    if unused:
        out.append("## Extracted Tables")
        out.append("")
        out.append("The following tables were detected by table extraction but could not be placed confidently in the article body.")
        out.append("")
        for table in unused:
            out.append(f"Table detected on page {table.page}.")
            out.append("")
            out.append("[table formatting approximate]")
            out.append("")
            out.append(table.markdown)
            out.append("")

    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md, stats


def has_garbled_math(line: str) -> bool:
    # Heuristic for repeated styled glyph extraction such as "𝐶𝐶" or "𝑅𝑅".
    return bool(re.search(r"([\U0001D400-\U0001D7FF])\1", line))


def convert_pdf(
    pdf_path: Path,
    output_path: Path,
    debug: bool = False,
    extract_table_data: bool = True,
    table_timeout: int = 5,
) -> dict:
    pages = extract_pages(pdf_path)
    lines, removed_running = remove_running_headers(pages)
    title = detect_title(lines, pdf_path)
    if extract_table_data:
        tables, table_warnings = extract_tables(pdf_path, per_page_timeout=table_timeout)
    else:
        tables, table_warnings = [], ["Table extraction disabled."]
    markdown, stats = group_lines_to_markdown(lines, title, tables)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    report = {
        "input": str(pdf_path),
        "output": str(output_path),
        "pages": len(pages),
        "title": title,
        "words": len(markdown.split()),
        "removed_running_lines": len(removed_running),
        **stats,
        "warnings": table_warnings,
    }
    if "[table formatting approximate]" in markdown:
        report["warnings"].append("One or more tables were marked approximate.")
    if "[equation extraction unclear]" in markdown:
        report["warnings"].append("One or more equations were marked unclear.")
    if debug:
        debug_path = output_path.with_suffix(".report.json")
        debug_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        report["debug_report"] = str(debug_path)
    return report


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Input PDF path.")
    parser.add_argument("-o", "--output", type=Path, help="Output Markdown path.")
    parser.add_argument("--debug", action="store_true", help="Write a JSON extraction report next to the Markdown file.")
    parser.add_argument("--no-tables", action="store_true", help="Skip pdfplumber table extraction.")
    parser.add_argument("--table-timeout", type=int, default=5, help="Seconds allowed for table extraction per page.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    pdf_path = args.pdf.resolve()
    if not pdf_path.exists():
        raise SystemExit(f"Input PDF does not exist: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise SystemExit(f"Input is not a PDF: {pdf_path}")
    output_path = args.output
    if output_path is None:
        output_path = Path("output/pdf") / f"{slugify(pdf_path)}_clean_structured.md"
    output_path = output_path.resolve()
    report = convert_pdf(
        pdf_path,
        output_path,
        debug=args.debug,
        extract_table_data=not args.no_tables,
        table_timeout=args.table_timeout,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
