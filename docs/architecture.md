# Ontology Curation Assistant Architecture

Last updated: 2026-06-17

## Current System

Ontology Curation Assistant is a local, human-in-the-loop curation app for bioprocess ontology development. The LLM can propose evidence-grounded ontology changes, but curator review and ODK validation remain the boundary before ontology implementation.

```text
Zotero/local files
  -> copied PDFs
  -> raw extracted Markdown
  -> cleaned canonical per-paper Markdown
  -> combined literature corpus
  -> LLM proposal request
  -> candidate review and matching
  -> approved ROBOT/ODK template export
```

## Implemented Modules

- `backend/app/main.py`: FastAPI app startup, static browser routes, runtime schema initialization.
- `backend/app/api/routes.py`: JSON APIs for configuration, Zotero, literature, ontology, prompt, extraction, candidates, OLS/local matches, exports, and ODK workflow.
- `backend/app/cli.py`: Typer commands for ingest, Zotero sync/import, literature pipeline/reset, extraction, suggestions, and ODK dry-run/apply workflows.
- `backend/app/config.py` and `backend/app/services/runtime_config.py`: environment settings plus SQLite-backed browser overrides.
- `backend/app/db/session.py` and `backend/app/models/db.py`: SQLAlchemy models, `create_all()`, and small idempotent SQLite schema additions. Alembic is not used.
- `backend/app/projects.py`: project-management service layer for project folder layout, active project selection, project type/parent hierarchy metadata, base IRI suggestions, minimal scope notes, path status readouts, tagged-literature counts, project curation runs, suggestion review, evaluation, and project ODK logging.
- `backend/app/zotero/*`: Zotero Web API metadata sync and normalization.
- `zotero_lit_md/*`: standalone Zotero Desktop/local-PDF Markdown exporter.
- `backend/app/BibPipelineCombined.py`: integrated PDF copy, PDF-to-Markdown, paper structuring, and legacy combine stages.
- `backend/app/literature/pipeline.py`: application wrapper that validates paths, preserves compatibility paths, clears generated working folders, calls the integrated pipeline, and writes the final combined corpus from canonical per-paper Markdown.
- `backend/app/literature/repository.py`: per-paper Markdown read/write, YAML front matter, repository loading, reset, and LLM corpus assembly.
- `backend/app/literature/cleanup.py`, `diagnostics.py`, and `literature_types.py`: Phase 2 cleanup, provenance, and extraction-quality records.
- `backend/app/ontology/local.py`, `matching.py`, and `ols.py`: local OBO/OWL/RDF/TSV indexing and OLS lookup.
- `backend/app/llm/service.py`, `curation.py`, and `ontology_suggestions.py`: mock/OpenAI-compatible LLM calls, editable curation prompt flow, and suggestion traces.
- `backend/app/odk/integration.py` and `workflow.py`: approved-candidate TSV/ROBOT export and safe ODK workflow orchestration.

## Literature Artefacts

The default compatible layout remains:

```text
literature/
  Paper-PDF/                 copied source PDFs
  Markdown/                  raw extracted Markdown from PDFs
  papers/                    cleaned canonical per-paper Markdown
  combined_literature.md     combined LLM corpus generated from papers/
  metadata/
    literature_index.json
    extraction_report.json
    cleanup_reports.json
```

The conceptual artefact roles are source PDF, raw extracted Markdown, cleaned canonical Markdown, combined literature Markdown, metadata index, cleanup report, and extraction diagnostics. The names remain compatible with existing installations unless overridden with `OCA_LITERATURE_*` settings.

## Phase 2 Behavior

Cleaned per-paper Markdown now carries Phase 2 provenance front matter where available: `paper_id`, `zotero_key`, title, authors, year, journal, DOI, `source_pdf`, `raw_markdown`, extraction method/date, cleanup version, and extraction quality. Missing values are rendered as empty strings or `null`; existing compatibility fields such as `id`, `source`, and `imported_at` are retained.

Cleanup is deterministic and conservative. It removes named publisher boilerplate such as `Open Access Article. Published on ...`, `View Article Online`, download lines, isolated page numbers, and known footer notices. It does not remove lines merely because they contain DOI values.

Diagnostics record page count when page markers exist, raw/cleaned character counts, abstract/section/reference detection, duplicate-line warnings, probable scanned or low-text extraction, cleanup rule counts, warnings, errors, and one of `usable`, `usable_with_warnings`, `failed`, or `requires_manual_review`.

The final combined corpus is generated from valid canonical `papers/*.md`, includes explicit `BEGIN_PAPER`/`END_PAPER` comments, de-duplicates by paper ID, excludes references by default for LLM context, and skips failed/manual-review papers rather than letting empty papers silently enter extraction.

## Current Limitations

- No OCR is implemented for likely scanned PDFs.
- Reading-order handling is best-effort PyMuPDF text/block extraction; the app records warnings but does not claim reliable two-column reconstruction.
- Project management currently provides metadata and UI scaffolding only. The active project is visible on the Dashboard and Projects page, and Zotero-backed literature can be tagged to projects, but literature import, candidate generation/review, ontology graph routing, real ontology imports, and ODK/ROBOT exports are not fully project-aware yet.
- Project dependency/import relationships and external reference ontology semantics are intentionally not modeled in project metadata. Actual ontology import/dependency handling is deferred to curation and ontology review.
- Relation persistence, evidence segment tables, formal migrations, authentication, reviewer roles, direct pull-request workflow, BFO validation, and a versioned relation catalogue remain planned.
- Later BFO support should target BFO 2020 identifiers and terminology.
- Later relation validation should use a version-controlled static YAML or JSON relation catalogue in the repository, optionally generated or checked against ontology imports.

## Phase 3 Proposal

Phase 3 should modify the existing LLM curation flow rather than creating a parallel implementation:

- Add explicit `bootstrap` and `curation` modes in `backend/app/llm/curation.py` and expose the selected mode through `/api/curation/prompt` or a nearby config endpoint in `backend/app/api/routes.py`.
- Introduce modular prompt profiles under `prompts/` and load them through `backend/app/llm/curation.py`; keep the final assembled prompt preview/edit path on the existing browser Curation Prompt page.
- Define a strict proposal schema in `schemas/` and validate responses in `backend/app/llm/curation.py` before candidate persistence.
- Keep raw request/response traces in `literature/curation_runs/`, with one controlled malformed-JSON repair attempt in the LLM service layer.
- Require evidence quotations tied to `paper_id` and verify those snippets against `backend/app/literature/repository.py` loaded content before persistence.
- Add component-specific confidence fields and operation types to the parsed candidate payload, while storing temporary candidate UUIDs only. The LLM must not generate permanent ontology IDs.
- Map accepted Phase 3 proposal operations into the existing candidate review and ODK export modules only after curator approval.
