# Code Overview

Last updated: 2026-06-03

## Application Entry

- `backend/app/main.py` creates the FastAPI app, initializes the runtime schema on startup, mounts `/static`, and serves the browser UI at `/`, `/config`, `/zotero`, `/literature`, `/ontology`, `/curation-prompt`, `/curation`, and `/export`.
- `backend/app/api/routes.py` contains the JSON API used by the browser UI.
- `backend/app/static/index.html`, `styles.css`, and `app.js` implement the dependency-light browser workflow.
- The static UI includes a shared top-bar logo, local-storage-backed theme selection, client-side route handling for header/dashboard links, page-scoped startup loading with visible startup/page errors, accessible click acknowledgement toasts, long-running button busy states, an editable curation prompt page, SVG graph rendering with persisted label/description controls, candidate rejection controls, and saved API configuration selection.
- `zotero_lit_md/` is a standalone CLI package exposed through `python -m zotero_lit_md`; it reads Zotero Desktop's local API for parent and child attachment keys, discovers stored PDFs from local Zotero storage folders on disk, extracts PDF text, and writes one LLM/RAG-ready Markdown file per PDF.

## Configuration Flow

- `backend/app/config.py` defines environment-backed settings with the `OCA_` prefix.
- `backend/app/services/runtime_config.py` overlays browser-saved settings from the `app_settings` table and masks secrets in API responses.
- Browser configuration endpoints save Zotero, LLM, local ontology path, and the Zotero literature source path without returning API keys in clear text.
- The browser Literature Pipeline Configuration exposes only the Zotero literature source path. Advanced pipeline output paths are still resolved from environment/runtime settings.
- The browser Curation Prompt page stores the editable prompt in `app_settings` as `curation_prompt_template`. `/api/curation/prompt` loads, saves, and resets it; `/api/curation/suggestions/run` uses it with the selected Existing Ontology `.obo` file and `combined_literature.md`.
- Saved API configurations are persisted as masked server-side entries in `app_settings`, with active Zotero/LLM configuration IDs.

## Zotero Flow

- `backend/app/zotero/client.py` wraps the Zotero Web API and follows pagination through Link headers.
- The Zotero client can fetch all items, one parent item, and child attachment items through the configured user or group library endpoint.
- `backend/app/zotero/importer.py` normalizes Zotero API or CSL-like records into `LiteratureSource` rows.
- `POST /api/zotero/sync` defaults to no limit and imports all records returned by the configured library or collection.
- `GET /api/zotero/entries` feeds the dedicated Literature/Zotero page. Entry payloads include a Zotero select URI only when the provider item key is valid and unambiguous, and the frontend renders title-first records with metadata and expandable per-record Markdown. Repository-only Markdown records created by the integrated PDF pipeline are appended so PDF imports are visible even without matching Zotero metadata rows.
- `backend/app/literature/exporter.py` builds an initial LLM-ready literature export from the runtime SQLite cache and creates the `literature/` folder automatically.
- `backend/app/literature/repository.py` manages the per-paper LLM-ready Markdown repository. It can reset the repository recursively, clear stale sidecars, clean deterministic extracted text, omit identifiable PDF artifacts and reference sections, write one `.md` file per paper with YAML front matter, load all valid Markdown files recursively while skipping malformed files with diagnostics, combine entries into one Markdown corpus for LLM calls, and convert canonical/legacy paper records into Markdown metadata plus abstract/notes/ontology-relevant sections.
- `backend/app/BibPipelineCombined.py` contains the integrated combined literature workflow. `backend/app/literature/pipeline.py` is a configuration/orchestration wrapper that integrates the original pipeline by importing and calling the `run_pipeline` function from `backend/app/BibPipelineCombined.py` while validating inputs.
- Section detection handles numbered headings, numbered subsections, canonical scientific headings, short standalone headings, front matter before the first heading, deterministic heading normalization, and section page ranges. Canonical output uses `content.sections`; page-level text is omitted by default unless `--include-pages` is used.
- `/api/zotero/entries` starts from Zotero rows in SQLite for stable source IDs, but merges each row with the matching Markdown repository entry when available. The frontend details panel displays Markdown content, the corresponding Markdown file path, and readable metadata.
- Browser literature ingestion, test Zotero import, browser Zotero sync, CLI ingest, CLI Zotero import, CLI Zotero link, and CLI Zotero sync refresh the Markdown repository after successful persistence. Zotero sync automatically triggers the PDF literature pipeline using the configured Zotero storage directory.
- `POST /api/literature/repository/reset` requires explicit confirmation and resets the configured literature base directory, including copied PDFs, generated Markdown, per-paper Markdown, combined Markdown, and stale sidecars, then clears stored literature rows/extraction state. The reset refuses root-like targets and does not follow symlinks. The Literature page exposes this action with a browser confirmation prompt, and `oca literature reset-repository --yes` exposes the same reset path from the CLI.
- `POST /api/config/literature` stores the runtime Zotero literature source path used by the integrated browser pipeline and clears hidden advanced path overrides so the browser flow returns to the original expected pipeline folders from that single input. `POST /api/literature/pipeline/run` runs the configured full pipeline and reports PDF copy, Markdown generation, per-paper repository, and combined output counts. The wrapper clears only the configured copied-PDF and generated-Markdown working folders under the literature base before calling the unchanged `BibPipelineCombined.run_pipeline`, making repeated sync/import runs idempotent. The CLI exposes the same pipeline through `oca literature pipeline` with optional one-off path overrides; `--base-dir` derives `Paper-PDF`, `Markdown`, `papers`, and `combined_literature.md` unless a specific folder option is supplied.
- `ontology_curation_assistant/__main__.py` exposes the same Typer CLI through `python -m ontology_curation_assistant`.

## Zotero Local Markdown Export

- `zotero_lit_md/cli.py` implements the argparse CLI with first-class commands for `pdf-to-md`, `folder-to-md`, `extract-zotero`, `extract-storage`, `trace-item`, and `doctor`. `pdf-to-md` and `folder-to-md` are API-free local PDF-to-Markdown commands; `extract-zotero` selects parent items by collection name/key, explicit item keys, or all items with PDF attachments; `extract-storage` bypasses the API and processes all PDFs or query-ranked PDFs from a Zotero storage folder; `trace-item` writes `zotero_lit_md_trace.json` with the parent-to-child-to-storage-to-PDF chain. Legacy compatibility commands remain available for `extract-one`, `scan-storage`, `extract-one-storage-key`, `extract-storage-folder`, `from-folder`, and top-level selection flags.
- `zotero_lit_md/local_pdf.py` is the API-free PDF foundation. It defines `ExtractedPage` and `ExtractedPdf`, discovers PDFs recursively or non-recursively, extracts page text with PyMuPDF, lightly cleans repeated blank lines/page numbers/headers/footers/hyphenated line breaks, converts detected scientific headings and figure/table captions to Markdown, builds local retrieval chunks, handles output filename collisions, and writes the required LLM-ready Markdown structure.
- `zotero_lit_md/zotero_client.py` implements `ZoteroLocalClient` against `http://127.0.0.1:23119/api/`, including connection testing against `users/0/items?limit=1&format=json`, item/collection/saved-search retrieval, child attachment lookup, PDF attachment filtering, linked-file path handling, and filesystem-first stored PDF discovery through `find_pdfs_for_attachment_key(storage_path, attachment_key, metadata)`. For stored attachments, Zotero API `path`, `filename`, `contentType`, and `title` fields are treated only as relevance hints; the resolver recursively scans `{storage_path}/{attachmentKey}/` for `.pdf`/`.PDF` files and sorts matches by metadata filename, `storage:` hint, title words, then alphabetically. `find_pdf_for_attachment_key(zotero_data_dir, ...)` remains as a backward-compatible wrapper.
- `zotero_lit_md/pdf_extractor.py` uses PyMuPDF first and `pypdf` as fallback. It extracts page-level text, applies a simple two-column reading-order heuristic for text blocks, retains page numbers internally, and marks encrypted, missing, or incomplete text in diagnostics rather than inventing content.
- `zotero_lit_md/text_cleaning.py` removes repeated running headers/footers and page numbers, fixes safe hyphenated line breaks, normalizes whitespace, detects section headings, and builds deterministic filesystem-safe filenames.
- `zotero_lit_md/markdown_writer.py` renders the required Markdown structure with parent item key, attachment key, PDF path, extraction diagnostics including extracted character count, abstract, keywords, concept-map scaffold, full paper body, retrieval chunks, claim units, optional JSON sidecars, optional combined corpus, and failure reports.
- `zotero_lit_md/chunking.py` and `zotero_lit_md/diagnostics.py` create page-aware retrieval chunks and conservative claim units only from extracted paper text.

## Existing Ontology Flow

- `backend/app/ontology/local.py` scans configured ontology folders and indexes supported files.
- RDF/OWL/Turtle files are parsed with `rdflib`.
- OBO and ROBOT/template TSV files are parsed with simple local readers.
- Indexed term payloads include term ID/IRI, label, definition, synonyms, parents, and source file.
- The browser Existing Ontology page calls `/api/ontology/status`, `/api/ontology/scan`, `/api/ontology/select-file`, `/api/ontology/index`, and term search endpoints.
- Ontology status reports selected-file parse errors, while term and search endpoints return controlled HTTP 400 responses if the selected ontology file cannot be parsed.
- `/api/ontology/graph` maps indexed terms to graph nodes and parent/subclass edges.
- `/api/meta-ontology/graph` returns the curation meta-model used by the dashboard graph.

## Candidate Flow

- `backend/app/extraction/service.py` persists validated candidate payloads.
- `backend/app/llm/service.py` provides deterministic mock extraction and an optional OpenAI-compatible chat-completions call.
- `backend/app/llm/curation.py` validates the saved curation prompt, selected `.obo` ontology file, and current `combined_literature.md`; assembles the final LLM request in deterministic sections; chunks oversized literature according to `OCA_LLM_CONTEXT_CHAR_LIMIT`; calls the configured OpenAI-compatible provider; validates JSON responses; and writes sanitized request plus response/raw-response traces under `literature/curation_runs/`.
- `backend/app/llm/ontology_suggestions.py` builds a complete literature export from the canonical Markdown repository, creates a traceable ontology-suggestion prompt, validates the required `suggestions` JSON shape, and supports a no-credentials dry run through `oca llm-ontology-suggestions`.
- Browser candidate extraction uses all valid LLM-ready Markdown literature files from the configured repository when no source is explicitly supplied. Empty repositories return a controlled import-literature-first error, and malformed Markdown files are skipped with warnings when valid files remain.
- Candidate records store curator edits, evidence, selected OLS match, selected local ontology match, lookup statuses, and curator decision.
- The default `/api/candidates` active queue returns only `new`, `in_review`, `needs_more_evidence`, and `deferred` records, so approved and rejected candidates are removed from the curation list after review.
- Candidate records also store permanent rejection timestamp and optional rejection reason.
- Active candidate listing excludes permanently rejected candidates by default.
- Temporary rejection is browser-session-only and hides the visible queue without changing persistent candidate state.
- OLS matching is implemented in `backend/app/ontology/ols.py`.
- Local PPO matching uses `backend/app/ontology/local.py`.
- Neither OLS nor local matches are auto-selected; the UI defaults to `Nothing selected`.
- Graph rendering is defensive: empty graph data displays an empty state, malformed edges are skipped, node/edge details are shown on click, and local-storage-backed controls can hide or restore text labels, node labels, edge labels, long descriptions, and less relevant placeholder nodes.

## Export Flow

- `backend/app/odk/integration.py` writes approved candidates as ROBOT-template TSV or simple candidate TSV.
- Exports include candidate label, definition, evidence, source document ID, selected OLS match, selected local ontology match, curator decision, mappings, and proposed parent/context.
- `backend/app/odk/integration.py` also validates the configured `OCA_PPO_ODK_ONTOLOGY_PATH` and can stage generated ontology artifacts beneath that directory.
- `backend/app/odk/workflow.py` is the safe implementation orchestrator. It selects only `approved` and `approved_with_edits` candidates, validates and audits an optional ontology-suggestion trace file, writes the configured ROBOT template, marks accepted candidates through `implemented`, `validated`, and `uploaded` states, runs the configured validation command, blocks upload on validation failure, and defaults to dry-run mode.
- `backend/app/github_export.py` saves generated ontology artifacts to GitHub through the contents API. It reads `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_BRANCH`, and optional `GITHUB_BASE_PATH`, supports create/update semantics, and returns commit metadata or clear configuration/API errors.
- `POST /api/odk/workflow` exposes the orchestrator to the browser/API. Non-dry-run calls require `production=true`. The CLI exposes the same path through `oca odk-apply-approved`, with `--no-dry-run --production` required for real validation/upload.
- `backend/app/audit/logging.py` appends secret-redacted JSONL audit events for candidate proposal/review/decision changes. The ODK workflow writes implementation, validation, stop, and upload events to the configured audit log.

## Persistence

- SQLAlchemy models live in `backend/app/models/db.py`.
- Runtime schema creation and small SQLite-compatible schema additions live in `backend/app/db/session.py`.
- The project does not yet use Alembic migrations.

## Tests

- Browser/API tests live in `backend/tests/test_browser_api.py`.
- Existing CLI, Zotero, extraction, ODK, and review policy tests remain in `backend/tests/`.
- `backend/tests/test_entry_generation.py` covers literature repository reset, deterministic LLM-ready extraction, PPO ODK artifact staging, mocked GitHub export, and one end-to-end ontology entry generation path.
- `backend/tests/test_odk_workflow.py` covers dry-run behavior, accepted-only implementation, rejected-candidate blocking, validation failure, validation success, upload gating, and audit ordering with mocked commands/uploads.
- `backend/tests/test_zotero_lit_md.py` covers API-free PDF/folder-to-Markdown extraction, PDF discovery, local Markdown rendering, heading and caption conversion, local chunk generation, output filename collisions, heading detection, header/footer removal, chunk behavior, filename sanitization, PDF attachment filtering, direct storage-path PDF resolution, query-filtered storage extraction, trace JSON, and section parsing for the standalone Zotero Markdown exporter.
