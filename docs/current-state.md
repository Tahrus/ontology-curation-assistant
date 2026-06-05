# Current Project State

Last reviewed: 2026-06-03

## Summary

Ontology Curation Assistant is currently an early working scaffold for a human-in-the-loop ontology curation workflow. The repository already has a FastAPI backend, a Typer command-line interface, SQLAlchemy-backed local persistence, ODK integration helpers, review policy logic, JSON schemas, prompt templates, and tests for the implemented slices.

The main implemented value today is a local browser workflow for configuration, Zotero metadata sync, local PPO ontology readout, candidate extraction/curation, OLS/local ontology matching, graph visualization, rejection management, and approved-candidate export, plus CLI support for the underlying ingestion and Zotero workflows. A standalone `zotero_lit_md` CLI package now exports Zotero Desktop local PDF attachments into full-text LLM/RAG-ready Markdown.

## Implemented Capabilities

### Backend API

The FastAPI application is defined in `backend/app/main.py`.

Implemented endpoints:

- `GET /health`: returns service health and app name.
- `GET /api/config`: returns selected runtime configuration, including ODK path status, ontology repository path, and human-approval setting.
- Browser pages: `/`, `/config`, `/zotero`, `/literature`, `/ontology`, `/curation-prompt`, `/curation`, `/export`.
- Browser UI includes client-side route handling for dashboard/header links, page-scoped startup data loading, a visible startup/page error path, accessible button/link click feedback, long-running action busy states, a Light/Dark theme toggle persisted in local storage, and a smaller shared logo link back to the dashboard.
- Configuration: `/api/config/status`, `/api/config/zotero`, `/api/config/llm`, `/api/config/ontology-path`, `/api/config/test-zotero`.
- Literature pipeline configuration is exposed through `/api/config/literature`. The browser-facing literature pipeline configuration only requires the local Zotero literature source path; advanced output paths remain environment-backed. The combined Zotero/PDF/Markdown pipeline can be run through `POST /api/literature/pipeline/run`.
- Saved API configurations: `/api/config/saved`, `/api/config/saved/{id}/activate`, and deletion.
- Zotero: `/api/zotero/test`, `/api/zotero/sync`, `/api/zotero/entries`, `/api/zotero/entries/{id}`, `/api/zotero/import-test`.
- Existing ontology: `/api/ontology/status`, `/api/ontology/scan`, `/api/ontology/select-file`, `/api/ontology/index`, `/api/ontology/terms`, `/api/ontology/terms/{term_id}`, `/api/ontology/search`, `/api/ontology/graph`.
- Existing ontology term and search endpoints return controlled client errors when the selected ontology file cannot be parsed, rather than leaking a raw server error into browser startup.
- Meta-ontology graph: `/api/meta-ontology/graph`.
- Curation prompt and suggestions: `/api/curation/prompt` for load/save/reset of the editable prompt and `/api/curation/suggestions/run` for the LLM curation request using the saved prompt, selected `.obo` ontology, and current `combined_literature.md`.
- Literature and candidates: `/api/literature`, `/api/extraction/candidates`, `/api/candidates`, `/api/candidates/{id}`, review, OLS matching, local ontology matching, match selection, and decision endpoints. The default active candidate queue includes draft/in-review/deferred/needs-more-evidence records and excludes approved or rejected records.
- Export: `/api/exports/approved.robot.tsv` and `/api/exports/approved.candidates.tsv`.
- ODK implementation workflow: `POST /api/odk/workflow` defaults to dry-run and requires `production=true` when `dry_run=false`.

The broader audit APIs remain planned.

### Command-Line Interface

The CLI entry point is `oca`, configured in `pyproject.toml` and implemented in `backend/app/cli.py`.

Implemented commands:

- `oca doctor`: prints app, database, ODK home, and ontology repository configuration.
- `oca odk-preview`: shows the target path where approved ROBOT templates would be exported.
- `oca odk-apply-approved`: dry-runs the approved-candidate implementation workflow by default. Real implementation, validation, and upload require `--no-dry-run --production`.
- `oca ingest <literature_dir>`: recursively registers files from a directory in the local database.
- `oca literature-list`: lists ingested literature documents.
- `oca literature-show <document_id>`: shows metadata and extracted text for one document.
- `oca extract-candidates <document_id>`: builds a curator-focused LLM prompt, supports prompt export, supports mock JSON output, validates candidate payloads, and persists valid candidate terms.
- `oca candidates-list`: lists persisted candidate terms.
- `oca candidate-show <candidate_id_or_db_id>`: shows full details for a persisted candidate term.
- `oca zotero-import <metadata_file>`: imports offline Zotero/Better BibTeX-style JSON metadata.
- `oca zotero-list`: lists imported literature source records.
- `oca zotero-show <source_id>`: shows full metadata for one source record.
- `oca zotero-link-documents <literature_dir>`: conservatively links already ingested documents to imported source records.
- `oca zotero-config`: shows Zotero API sync configuration without printing the API key.
- `oca zotero-sync`: syncs metadata from the Zotero Web API into local source records.
- Literature-changing CLI workflows refresh the LLM-ready Markdown repository under `literature/papers` by default. Each paper is stored as a deterministic `.md` file with YAML front matter for stable metadata and Markdown sections for abstract, notes, and ontology-relevant extracted content.
- Candidate extraction loads Markdown repository files and combines them into one Markdown corpus for the LLM. The former literature JSON sidecar has been removed and is no longer generated or read.
- `oca literature reset-repository --yes` and `POST /api/literature/repository/reset` reset the configured literature base directory recursively, recreate the empty directory, clear stored literature rows/extraction state, log deleted items, refuse unsafe root-like targets, unlink symlinks instead of following them, and leave ontology outputs, settings, GitHub configuration, and ODK files untouched when those outputs are outside the literature base.
- `oca literature pipeline` runs the integrated combined literature pipeline from configured paths: Zotero storage PDF import, PDF-to-Markdown conversion with PyMuPDF, per-paper Markdown creation for PDF-only imports, generated full-text merge into per-paper Markdown, and final combined Markdown corpus creation. A CLI `--base-dir` override derives the original `Paper-PDF`, `Markdown`, `papers`, and `combined_literature.md` paths from that base unless a more specific path is supplied. The wrapper clears only `Paper-PDF` and `Markdown` under the configured literature base before invoking the unchanged `BibPipelineCombined.run_pipeline`, so repeated runs refresh artifacts without duplicating copied PDFs.
- `oca llm-ontology-suggestions` creates a traceable ontology-suggestion prompt/export from the canonical Markdown literature repository. `--dry-run` needs no credentials and writes a schema-valid empty suggestion payload; non-dry-run mode requires configured OpenAI-compatible LLM credentials and validates the required `suggestions` JSON shape.
- `python -m zotero_lit_md pdf-to-md` and `folder-to-md`: API-free local PDF extraction commands that convert one PDF or all PDFs in a folder into LLM/RAG-ready Markdown using PyMuPDF, light text cleanup, heading/caption conversion, diagnostics, and retrieval chunks.
- `python -m zotero_lit_md extract-zotero`: connects to the Zotero Desktop local API, selects papers by collection name/key, explicit item keys, or all items with PDF attachments, uses the API only to identify parent items and child attachment keys/metadata, discovers stored PDFs from `{storage_path}/{attachment_key}/`, extracts local PDF text, and writes LLM/RAG-ready Markdown files with optional JSON sidecars and combined corpus output.
- `python -m zotero_lit_md extract-storage`, `trace-item`, and `doctor`: bypass the API for direct storage-folder extraction with `--all-pdfs` or `--query`, write a JSON trace for one Zotero parent item's item-to-attachment-to-PDF mapping, and diagnose local storage/PDF extraction before API checks. Legacy compatibility commands remain available for `extract-one`, `scan-storage`, `extract-one-storage-key`, `extract-storage-folder`, and `from-folder`.
- `docs/odk-workflow-and-code-overview.md`: self-contained implementation and ODK workflow overview.

Supported ingestion content extraction:

- Plain text-like files: `.txt`, `.md`, `.tsv`, `.csv`
- PDFs via `pypdf`

Other file types can be registered with metadata, but no text content is extracted from them yet.

### Persistence

Database setup lives in `backend/app/db/session.py`.

Current default database:

- SQLite at `sqlite:///./oca.sqlite3`

Implemented SQLAlchemy tables:

- `literature_documents`
- `literature_sources`
- `extraction_runs`
- `candidate_terms`
- `app_settings`

Stored document fields:

- `id`
- `path`
- `filename`
- `suffix`
- `size_bytes`
- `content`
- `created_at`

The larger intended schema is described in `docs/database-schema.md`. Literature sources, extraction runs, and candidate terms now have persistence tables, including browser curation fields for selected OLS match, selected local ontology match, lookup statuses, curator decision, rejection reason, and permanent rejection timestamp. Richer evidence segmentation, audit events, and formal migrations are still planned.

### Zotero Literature Sources

The current Zotero integration supports both offline imports and metadata-only Web API sync.

Implemented:

- Import from CSL JSON-like Zotero/Better BibTeX exports.
- Import from a Zotero Web-API-like JSON item shape when present in exported files.
- Metadata-only sync from Zotero user or group libraries through the Zotero Web API.
- Direct local extraction from deposited Zotero PDF attachments after metadata sync/import. Parent items can be resolved by stored Zotero item key, stored Zotero URI, exact title, normalized title, or DOI. Child attachments are inspected through Zotero metadata, but extraction reads the local PDF file path directly rather than DOI, publisher, or web links.
- Browser sync defaults to no limit and follows Zotero pagination until all configured records are fetched.
- Browser literature records are shown by title with author/year/type/DOI/key metadata, an `Open in Zotero` URI only when a Zotero item key is valid and unambiguous, and an expandable JSON section for the corresponding record payload.
- The browser literature view merges Zotero database rows with matching Markdown repository entries when available and also displays repository-only Markdown records created by the integrated PDF import pipeline. The detail panel shows Markdown content and readable metadata rather than raw JSON. Candidate extraction from a Zotero source prefers the Markdown record over legacy metadata snippets.
- Browser literature ingestion, test imports, and Zotero sync refresh the Markdown repository in `literature/papers`; the export folder is created automatically. Zotero sync also automatically triggers the Zotero PDF literature pipeline using the configured Zotero storage directory.
- Optional collection sync through configured or CLI-provided collection keys.
- Secret-safe `zotero-config` output.
- Pagination through Zotero `Link` headers.
- API errors for missing config, authentication failures, not-found responses, network failures, and invalid JSON.
- Storage of provider item key, citation key, title, creators, year, DOI, URL, abstract, tags, and collections.
- Storage of Zotero item type, Zotero item version, and sync timestamp when provided by API sync.
- Conservative document linking by citation key in filename, DOI in content, or exact normalized title in filename/content.
- Ambiguous links are skipped.
- Existing document links are not overwritten unless `--force` is used.

Not implemented:

- Reading Zotero's internal local database.
- Downloading missing PDF attachments from Zotero or publisher sites.
- Writing changes back to Zotero.

### Domain Models and Contracts

Implemented Pydantic/domain objects:

- `CandidateTerm`
- `Evidence`
- `ReviewStatus`
- `ExtractionMetadata`
- `ExtractedClaim`
- `AuditEvent`
- `OntologyMatch`

Important current rule:

- `approved` and `approved_with_edits` are the only exportable review statuses.

This rule is implemented in `backend/app/review/policy.py`.

### ODK Integration

ODK helper code lives in `backend/app/odk/integration.py`.

Implemented:

- `OdkProjectConfig`
- `preview_export_path()`
- `build_command_candidates()`

Current behavior can compute the configured export path and generate downloadable approved-candidate TSV/ROBOT-template TSV from the browser API.

The safe implementation workflow now lives in `backend/app/odk/workflow.py`. It selects only `approved` and `approved_with_edits` candidates, optionally validates/references an ontology-suggestion trace file in the workflow audit, writes the configured ROBOT template into the configured PPO ODK ontology path, runs the configured validation command, blocks upload on validation failure, and uploads through the configured GitHub mechanism only after validation succeeds. Dry-run is the default.

Default configured paths:

- `OCA_ODK_HOME`: `C:\Users\ge47vob\ontology-development-kit`
- Template directory: `src/ontology/templates`
- Default approved-term template: `ai_approved_terms.tsv`
- Default workflow template relative path: `templates/ai_approved_terms.tsv`
- Default validation command: `make test`
- Default workflow mode: dry-run

### Ontology Matching

Implemented in `backend/app/ontology/matching.py` and `backend/app/ontology/local.py`:

- Exact label matching against a supplied dictionary of existing ontology terms.
- Local ontology folder scanning for `.owl`, `.rdf`, `.ttl`, `.obo`, and `.tsv`.
- RDF/OWL/Turtle parsing through `rdflib`.
- Simple OBO and ROBOT/template TSV readout.
- Term extraction for ID/IRI, label, definition, synonyms, parents, and source file.
- Local candidate matching by label/synonym similarity.
- Browser OLS matching through EMBL-EBI OLS4.
- Ontology and meta-ontology graph payloads for SVG graph rendering in the browser.

Local and OLS matches are never auto-selected. Curators must explicitly choose a match or mark a candidate as a new term proposal.

### Extraction

The current extraction implementation is a structured, testable scaffold.

Implemented:

- Prompt templates in `prompts/extraction/`
- JSON schemas in `schemas/`
- Pydantic extraction contracts
- Curator-focused prompt generation with bounded document context
- Mock-output JSON parsing for tests and local development
- Pydantic validation for labels, confidence scores, evidence, and `direct_or_inferred`
- Persistence of validated candidate terms and extraction runs

Implemented browser extraction:

- Deterministic mock extraction for local testing without API keys.
- Optional OpenAI-compatible chat-completions call when LLM provider/API key are configured.
- The editable ontology curation prompt page assembles LLM requests in deterministic order: saved prompt, selected current ontology OBO content, `combined_literature.md`, and a JSON-only output requirement. Missing/empty literature, missing LLM credentials, or missing/non-OBO selected ontology files fail before the LLM call. Oversized literature is chunked explicitly using `OCA_LLM_CONTEXT_CHAR_LIMIT`; request traces and valid/invalid responses are written under `literature/curation_runs/` without API keys.
- Browser extraction no longer requires selecting an individual literature document or paper. When no source is passed, it loads all valid LLM-ready Markdown files from the configured literature repository, skips malformed files with warnings, combines valid entries into one Markdown corpus, and returns a controlled import-literature-first message when no valid files are available.

Not implemented yet:

- Relation extraction persistence

## Repository Layout

```text
backend/
  app/
    api/          FastAPI routes
    audit/        audit event model
    db/           SQLAlchemy engine/session setup
    extraction/   extraction contracts
    models/       Pydantic and SQLAlchemy models
    odk/          ODK integration helpers
    ontology/     ontology matching helpers
    review/       review/export policy
    cli.py        Typer CLI
    config.py     environment-based settings
    main.py       FastAPI application
  tests/          pytest suite
docs/             architecture and workflow documentation
examples/         example review template
literature/       local source literature files
prompts/          extraction prompt templates
schemas/          JSON schemas for candidates
docker/           container scaffold
```

## Configuration

Settings are loaded from environment variables and `.env` through `pydantic-settings`.

Environment prefix:

- `OCA_`

Important settings:

- `OCA_DATABASE_URL`
- `OCA_ODK_HOME`
- `OCA_ONTOLOGY_REPO`
- `OCA_LOCAL_ONTOLOGY_PATH`
- `OCA_TEMPLATE_DIR`
- `OCA_DEFAULT_TEMPLATE_FILE`
- `OCA_GIT_BRANCH_PREFIX`
- `OCA_REQUIRE_HUMAN_APPROVAL`
- `OCA_LLM_PROVIDER`
- `OCA_LLM_API_KEY`
- `OCA_LLM_MODEL`
- `OCA_LLM_BASE_URL`
- `OCA_LLM_CONTEXT_CHAR_LIMIT`
- `OCA_ZOTERO_LIBRARY_TYPE`
- `OCA_ZOTERO_LIBRARY_ID`
- `OCA_ZOTERO_API_KEY`
- `OCA_ZOTERO_COLLECTION_KEY`
- `OCA_ZOTERO_API_BASE_URL`
- `OCA_ZOTERO_LITERATURE_STORAGE_PATH`, the only literature pipeline path routinely exposed in the browser configuration UI
- `OCA_ZOTERO_LINKED_ATTACHMENT_BASE_DIR`
- `OCA_LITERATURE_BASE_DIR`
- `OCA_LITERATURE_PDF_DIR`
- `OCA_LITERATURE_GENERATED_MD_DIR`
- `OCA_LITERATURE_REPOSITORY_PATH` for the per-paper Markdown repository
- `OCA_LITERATURE_COMBINED_OUTPUT_FILE`
- `OCA_LITERATURE_FUZZY_MIN_SCORE`
- `PPO_ODK_ONTOLOGY_PATH`
- `OCA_PPO_ODK_ONTOLOGY_PATH`
- `OCA_ODK_TEMPLATE_RELATIVE_PATH`
- `OCA_ODK_VALIDATION_COMMAND`
- `OCA_ODK_WORKFLOW_DRY_RUN`
- `OCA_ODK_UPLOAD_MODE`
- `OCA_ODK_AUDIT_LOG_PATH`
- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`
- `GITHUB_BRANCH`
- `GITHUB_BASE_PATH`

The project currently includes `.env.example` and a local `.env`.

The standalone Zotero Markdown exporter depends on `requests` for Zotero local API calls and PyMuPDF for primary PDF text extraction, with `pypdf` as fallback. Its Zotero storage directory is passed with `--storage-path`; legacy commands can still resolve the Zotero data directory from `--zotero-data-dir`, `ZOTERO_DATA_DIR`, or common `~/Zotero` locations. The Zotero local API is treated as a parent/attachment-key index; stored Zotero PDFs are discovered by scanning the matching local storage attachment folder on disk. The integrated app pipeline in `backend/app/literature/pipeline.py` uses `OCA_ZOTERO_LITERATURE_STORAGE_PATH` plus configured `OCA_LITERATURE_*` paths and writes `literature/combined_literature.md` by default. When only PDFs are available, it creates valid per-paper Markdown records in the repository before combining the corpus. Pipeline errors are surfaced clearly for missing storage configuration, nonexistent paths, empty PDF discovery, failed copying, failed Markdown generation, and failed combined-corpus creation.

## Tests

Current test command:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Verified on 2026-06-02:

- 144 tests passed, including the full browser/API, Zotero, standalone Zotero Markdown exporter, literature Markdown, ODK workflow, and entry-generation workflow coverage.
- Ruff passed.

Covered by tests:

- CLI ingest error handling
- CLI ingest of a text file
- CLI literature-show missing document behavior
- Prompt generation
- Mock candidate extraction
- Candidate persistence
- Candidate duplicate skipping
- Candidate list/show CLI behavior
- Candidate extraction validation failures
- Zotero metadata import and duplicate update behavior
- Zotero Web API URL/header construction
- Zotero Web API item normalization and non-bibliographic item filtering
- Zotero Web API dry-run and persistence paths without network access
- Zotero Web API pagination and error handling
- Zotero source list/show CLI behavior
- Conservative document linking by citation key and DOI
- Ambiguous Zotero link skipping
- ODK preview path generation
- Export policy for approved versus non-approved candidate statuses
- Browser page routing
- Secret masking in config APIs
- Zotero browser sync defaulting to no artificial limit
- OLS lookup not auto-selecting the first match
- Local ontology scan/index/search on fixture files
- Local ontology match selection defaulting to nothing selected
- Export fields for selected local/OLS matches and curator decision
- Approved and rejected candidates leaving the active curation queue
- Saved API configuration masking and activation
- Permanent candidate rejection and restore
- Static JavaScript regression coverage ensuring `.casefold()` is not used, current routes are present, theme persistence is wired, and literature Markdown/Zotero controls are rendered
- Literature Markdown repository creation, stable paper IDs, front matter metadata, full-text export, hierarchical PDF text section extraction, page-range assignment, compact provenance, canonical schema migration, duplicate-section removal, metadata preservation, failure diagnostics, and Zotero key ambiguity handling
- Markdown repository loading, exact identifier/title matching, normalized-title ambiguity detection, section-first display fallback order, content hashes, and API exposure of canonical `content` diagnostics
- Graph endpoint shape for ontology and meta-ontology views, plus persisted browser controls for text labels, node labels, edge labels, descriptions, and simplified views
- Literature repository reset for existing Markdown files, nested files, empty repositories, missing repository paths, and stale sidecars, including preservation of unrelated ontology output files
- Repository-backed extraction without selected literature, with controlled empty-repository errors and malformed-Markdown warnings
- Configurable integrated literature pipeline path resolution, missing Zotero storage validation, combined Markdown corpus metadata, and API-side pipeline run validation
- Browser workspace regression coverage for missing Markdown records so Zotero entries and source-based extraction still load from metadata fallback
- Deterministic LLM-ready paper extraction with section/subsection hierarchy and artifact/reference omission
- GitHub ontology save/export behavior with mocked API calls and clear configuration errors
- ODK workflow dry-run, accepted-only implementation, rejected-candidate blocking, validation failure, validation success, upload gating, and audit ordering with mocked commands/uploads
- Full entry-generation workflow: reset literature repository, import sample paper, load per-paper Markdown, generate a candidate, stage PPO ODK output, and mock GitHub save
- Standalone Zotero Markdown exporter coverage for API-free PDF/folder-to-Markdown extraction, recursive and non-recursive PDF discovery, local Markdown rendering, output filename collision handling, heading/caption conversion, local retrieval chunks, heading detection, repeated header/footer removal, deterministic filename sanitization, filesystem-first stored and linked PDF path resolution, direct `--storage-path` extraction, query-filtered storage extraction, trace JSON generation, recursive storage scanning, storage-only extraction commands, PDF attachment filtering, doctor output formatting, and section parsing.

## Known Gaps

The project is not yet a full ontology curation application. The following pieces are documented or scaffolded but not fully implemented:

- Relation persistence tables
- Evidence segment storage
- Downloading missing Zotero attachments
- Writing changes back to Zotero
- Full production-grade AI/LLM extraction execution and retries
- Audit log persistence
- Direct branch management and pull request workflow
- Production GitHub export UI for generated ontology artifacts
- Authentication and reviewer roles
- Alembic migrations
- Production deployment configuration

## Current Safety Posture

The core safety boundary is already represented in code and tests:

- AI-generated or automatically extracted candidates are not treated as ontology changes.
- Only `approved` and `approved_with_edits` candidates are exportable.
- Current ODK functionality is preview-only, so the assistant does not mutate an ontology repository.

## Recommended Next Steps

1. Add Alembic and formal migrations for the existing `literature_documents` table.
2. Add richer evidence segment storage and review decision tables.
3. Add persisted ontology index tables if indexing large ontologies becomes slow.
4. Add optional tooling to detect missing local Zotero attachments and report how to repair them outside the extraction path.
5. Harden the OpenAI-compatible LLM provider with retries, model validation, and structured-output support.
6. Add direct ODK repository write/validation actions for approved candidates only.
7. Add validation around exported rows and map validation errors back to candidate IDs.
