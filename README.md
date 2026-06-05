# Ontology Curation Assistant

Human-in-the-loop software scaffold for AI-assisted ontology development with ODK-compatible exports.

This project helps ontology developers ingest scientific literature, extract candidate ontology terms and relations, review them with domain experts, and export only approved content into ODK/ROBOT-friendly files.

## Current Status

This is a project scaffold with:

- FastAPI backend structure
- Typer CLI entrypoint
- standalone `zotero_lit_md` CLI package for Zotero Desktop local-PDF Markdown export
- SQLite/PostgreSQL-ready settings
- JSON schemas for candidate terms and relations
- prompt templates for reproducible extraction
- ODK integration configuration pointing to `C:\Users\ge47vob\ontology-development-kit`
- documentation for architecture, workflow, and ODK integration
- starter tests

See [docs/current-state.md](docs/current-state.md) for a snapshot of what is implemented now versus what is still planned.

AI suggestions are intentionally separated from approved ontology exports.

## Layout

```text
ontology-curation-assistant/
  backend/
    app/
      api/
      audit/
      config.py
      extraction/
      main.py
      models/
      odk/
      ontology/
      review/
      services/
    tests/
  docs/
  examples/
  prompts/
  schemas/
  pyproject.toml
  .env.example
```

## Quick Start

```powershell
cd "C:\Users\ge47vob\.antigravity\ontology-curation-assistant"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
oca --help
uvicorn backend.app.main:app --reload
```

Open <http://127.0.0.1:8000/> after the server starts. Routine curation should not require more PowerShell commands after launch.

## Zotero Local PDF Markdown Export

The repository also includes a standalone command-line exporter for creating full-text, LLM/RAG-ready Markdown from Zotero Desktop's local API and locally stored PDF attachments:

```powershell
python -m zotero_lit_md extract-zotero --collection "Protein precipitation" --storage-path "C:\Users\<USER>\Zotero\storage" --output .\literature_md --verbose
python -m zotero_lit_md extract-zotero --collection-key COLLECTIONKEY --storage-path "C:\Users\<USER>\Zotero\storage" --output .\literature_md
python -m zotero_lit_md extract-zotero --item-keys ABCD1234 EFGH5678 --storage-path "C:\Users\<USER>\Zotero\storage" --output .\literature_md --json-sidecar
python -m zotero_lit_md extract-storage --storage-path "C:\Users\<USER>\Zotero\storage" --output .\literature_md --all-pdfs
python -m zotero_lit_md extract-storage --storage-path "C:\Users\<USER>\Zotero\storage" --output .\literature_md --query "protein precipitation"
python -m zotero_lit_md pdf-to-md --pdf "C:\path\to\paper.pdf" --output .\literature_md --verbose
python -m zotero_lit_md folder-to-md --folder "C:\Users\<USER>\Zotero\storage" --output .\literature_md --recursive --verbose
python -m zotero_lit_md trace-item --item-key ABCD1234 --storage-path "C:\Users\<USER>\Zotero\storage" --output .\trace_out --verbose
python -m zotero_lit_md doctor --storage-path "C:\Users\<USER>\Zotero\storage" --verbose
python -m zotero_lit_md from-folder .\pdfs --output .\literature_md
```

The API-free foundation commands are `pdf-to-md` and `folder-to-md`: they open local PDFs from disk with PyMuPDF, extract the PDF text layer, clean headings/captions lightly, and write LLM/RAG-ready Markdown without contacting Zotero. The exporter uses `http://127.0.0.1:23119/api/` only for Zotero-guided extraction. It does not require Zotero cloud credentials and does not call publisher websites. The Zotero local API is used as an indexing layer for parent items and child attachment keys only. Actual stored-PDF discovery is filesystem-first: the exporter inspects `{storage path}\{attachmentKey}\` and opens the discovered `.pdf` files from disk with PyMuPDF. `extract-storage` bypasses the API entirely for local storage fallback extraction.

## Browser Workflow

The browser UI is split into small pages:

- Dashboard: local status and links to the main workflows.
- Configuration: Zotero metadata sync settings, LLM/chatbot settings, Zotero connection testing, Zotero metadata sync, and the local Zotero literature source path used for PDF import.
- Literature: searchable list of imported or synced Zotero records with titles, Zotero links, and per-record Markdown inspection.
- Existing Ontology: local PPO ontology path, detected ontology files, indexing, and term search.
- Curation Prompt: editable ontology-curation LLM prompt and run controls.
- Curation: document ingestion, candidate extraction, candidate editing, local PPO matching, and external OLS matching.
- Export: approved candidate downloads for ROBOT/ODK/Protégé-oriented workflows.

The header includes a consistent logo link back to the Dashboard and a Light/Dark theme toggle. Theme choice is stored in browser local storage; if no choice exists, the UI follows the system color-scheme preference. Header and dashboard navigation use the static app's current client-side route map, so switching pages updates the visible workflow immediately without requiring a browser refresh.
Startup loads the dashboard status first and then only the current page's data, so an optional workflow error such as an unparsable selected ontology file is shown as a visible message instead of leaving the local workspace loading indicator in place.
Buttons, links, and other clickable controls provide visible pressed feedback plus an accessible status toast. Long-running actions disable their button, show a running label immediately, and report completion or errors in text.

The workflow supports:

- review backend, database, Zotero, and LLM readiness in Application Status
- save Zotero credentials and LLM/chatbot credentials in Configuration
- test Zotero credentials, sync all configured Zotero records, load local test Zotero entries, or import local Zotero PDFs into Markdown
- view synced/imported Zotero records, open them in Zotero when an item key is available, and inspect the Markdown record used by the UI
- scan and index a local PPO ontology folder, defaulting to `C:\Users\ge47vob\ontology-development-kit\target\ppo`
- inspect ontology and curation meta-model graphs with pan, zoom, node selection, and edge selection
- review, edit, save, reset, and run the ontology curation prompt before sending ontology/literature context to an LLM
- ingest a server-side literature file path or paste extracted text/notes into the Literature panel
- extract candidates from all valid LLM-ready literature Markdown files in the repository without selecting an individual paper
- run deterministic mock extraction, or use an OpenAI-compatible LLM when configured
- create candidates manually or generate a draft candidate from a curator nudge
- edit labels, definitions, rationales, source evidence, synonyms, parents, and mappings
- compare candidates against local PPO terms and external EMBL-EBI OLS terms
- approve, reject, defer, or mark candidates as needing more evidence
- intentionally select an existing local/OLS match or leave `Nothing selected`
- export approved candidates as `approved_candidates.robot.tsv` or `approved_candidates.tsv`

The UI calls JSON endpoints under `/api/...`, so CLI-created candidates and browser-edited candidates use the same SQLite database.
Credentials entered in the UI are stored in the local SQLite database for development use and are masked in API responses.
Saved API configurations are listed on the Configuration page with provider/library/model metadata, masked secrets, timestamps, and active-state controls.

Literature import, ingestion, linking, and Zotero sync workflows refresh the LLM-ready literature repository at:

```text
literature/papers
```

The folder is created automatically when needed. Each imported paper is saved as a separate `.md` file with YAML front matter for stable metadata (`id`, title, authors, year, DOI/PMID, source, URL, and import time), followed by human-readable Markdown sections for abstract, notes, and ontology-relevant extracted content. Filenames are deterministic and filesystem-safe, preferring DOI, PMID, stable literature ID, or a title-derived slug with a short digest.

The SQLite tables are runtime cache and workflow state. Literature content handed to an LLM is loaded from the Markdown repository, combined into a single Markdown corpus headed `# Literature Corpus`, and separated by literature entry ID and source filename. The Literature page shows Markdown-oriented records and metadata for human review instead of exposing raw JSON.

The app also writes one compact LLM-ready Markdown file per paper under:

```text
literature/papers/*.md
```

Each per-paper file uses this shape:

```markdown
---
id: "literature-id"
title: "Article title"
authors:
  - "Author One"
year: 2024
doi: "10.xxxx/example"
source: "Ontology Curation Assistant"
imported_at: "2026-06-02T12:00:00+00:00"
---

# Article title

## Abstract

...

## Notes

...

## Extracted ontology-relevant information

### Introduction

...
```

The per-paper repository omits page-wise chunks, running headers/footers, page numbers, references, and publisher boilerplate where the local deterministic cleaner can identify them. Candidate extraction uses all valid Markdown files in this repository automatically. Malformed Markdown files are reported and skipped when at least one valid file is available; if none are valid, the UI asks you to import literature first. Reset the literature workspace from the Literature page with explicit confirmation, or from the CLI:

```powershell
oca literature reset-repository --yes
```

The reset clears every file and subfolder under the configured `OCA_LITERATURE_BASE_DIR` literature directory, recreates the empty directory, and clears the runtime literature/candidate cache. It refuses unsafe reset targets such as filesystem roots and unlinks symlinks instead of following them.

Run the integrated Zotero PDF-to-Markdown pipeline from the browser by setting `Zotero literature source` on the Configuration page and clicking `Import Zotero PDFs`, or from the CLI:

```powershell
oca literature pipeline
oca literature pipeline --zotero-storage-dir "C:\Users\<USER>\Zotero\storage" --combined-output-file .\literature\combined_literature.md
```

The pipeline copies PDFs from the configured Zotero literature storage path into `literature/Paper-PDF`, converts those PDFs to section-structured Markdown in `literature/Markdown`, creates any missing per-paper repository Markdown records under `literature/papers`, merges matching generated full text, and writes one comprehensive combined Markdown corpus at `literature/combined_literature.md`. It fails with clear text if the Zotero source is missing, does not exist, contains no PDFs, copies no PDFs, generates no Markdown, or cannot write the combined corpus. It does not create or use a literature JSON sidecar. Before each import run, the wrapper clears only the configured copied-PDF and generated-Markdown working folders under the literature base directory, then calls the unchanged `BibPipelineCombined.run_pipeline`; repeated sync/import runs refresh the same artifacts instead of creating duplicate `_1` files.

### Zotero from the Browser

In Configuration > Zotero Metadata Sync, enter:

- Zotero library type: `user` or `group`
- Zotero user ID or group ID
- Zotero API key, if needed for the target library
- optional collection key

Use Zotero Connection to test the credentials, then click `Sync All Zotero Records`. The browser sync defaults to no limit and follows Zotero pagination until all records in the configured library or collection are retrieved. An advanced optional limit is available only for testing. Sync refreshes the Markdown files in `literature/papers`.

If you do not have real Zotero credentials ready, click `Load Test Entries`; this imports two local bibliography records that are enough to test selection and mock extraction.

In Configuration > Literature Pipeline Configuration, only `Zotero literature source` is required for the integrated PDF import flow. Point it at the local Zotero `storage` folder, then click `Import Zotero PDFs`. Advanced output paths still come from environment settings when needed, but they are not exposed in the routine browser workflow.

### LLM / Chatbot Configuration

In API Key Configuration, enter:

- provider: `openai` or `openai-compatible`
- API key
- optional model name, such as `gpt-4o-mini`
- optional OpenAI-compatible base URL
- optional context character limit through `OCA_LLM_CONTEXT_CHAR_LIMIT`

If no LLM key is configured, Candidate Extraction still works through a deterministic mock extractor. Select `Use configured LLM` only when you want the backend to call the configured OpenAI-compatible chat completions endpoint.

### Candidate Extraction and Curation

Add optional guidance, then click `Extract Candidates`. The backend combines all valid LLM-ready Markdown files in the configured literature repository automatically. Draft, in-review, deferred, and needs-more-evidence candidates appear in Candidate Curation, where you can edit all curator-facing fields, add a manual candidate, approve/reject candidates, and run OLS checks. Approved and rejected candidates leave the active curation queue. Use `Run OLS For Draft Candidates` to batch-check draft candidates.

Open <http://127.0.0.1:8000/curation-prompt> to review the ontology curation prompt before running the LLM suggestion workflow. The saved prompt is stored in local application settings and is assembled deterministically with the selected existing ontology `.obo` file and the current `literature/combined_literature.md` file. Missing or empty literature, missing LLM credentials, or a missing/non-OBO selected ontology file stops the request before any LLM call. Request traces and parsed responses are written under `literature/curation_runs/`; invalid JSON responses are preserved as raw text for debugging. The selected OBO file is read-only during suggestion generation.

### Existing PPO Ontology

Open <http://127.0.0.1:8000/ontology> to configure and inspect the local ontology. The default/example path is:

```text
C:\Users\ge47vob\ontology-development-kit\target\ppo
```

The ontology page scans for supported files:

- `.owl`, `.rdf`, `.ttl`
- `.obo`
- ROBOT/template `.tsv`

After selecting a file, click `Index Selected Ontology`. The app extracts term IDs/IRIs, labels, definitions, synonyms, parent IDs when available, and source file metadata. This is local readout only; Protégé is not required.

The ontology page also includes a graph view. Terms are nodes and parent/subclass relationships are edges. Use mouse wheel zoom, drag pan, and click nodes or edges for details. Graph controls can hide or show text labels, node labels, edge labels, descriptions, and simplified placeholder nodes; toggle state is stored in browser local storage. The Dashboard includes a compact meta-ontology graph showing how sources, evidence, candidates, matches, decisions, and exports relate.

Local PPO matching differs from OLS matching:

- Local PPO matching checks candidates against the ontology file selected on the Existing Ontology page.
- OLS matching checks external EMBL-EBI OLS results.
- Both default to `Nothing selected`; no first result is automatically selected.
- Leaving `Nothing selected` means no existing term has been chosen yet, and the candidate still needs curator review or can be explicitly marked `propose_new_term`.

Useful endpoints include:

```text
GET    /api/config/status
POST   /api/config/zotero
POST   /api/config/llm
POST   /api/config/ontology-path
POST   /api/config/literature
GET    /api/curation/prompt
POST   /api/curation/prompt
DELETE /api/curation/prompt
GET    /api/config/saved
POST   /api/config/saved
POST   /api/config/saved/{id}/activate
DELETE /api/config/saved/{id}
POST   /api/config/test-zotero
POST   /api/zotero/test
POST   /api/zotero/sync
GET    /api/zotero/entries
GET    /api/zotero/entries/{id}
POST   /api/zotero/import-test
GET    /api/ontology/status
POST   /api/ontology/scan
POST   /api/ontology/select-file
POST   /api/ontology/index
GET    /api/ontology/terms
GET    /api/ontology/terms/{term_id}
GET    /api/ontology/search?q=...
GET    /api/ontology/graph
GET    /api/meta-ontology/graph
GET    /api/literature
POST   /api/literature
POST   /api/literature/pipeline/run
POST   /api/curation/suggestions/run
POST   /api/extraction/candidates
GET    /api/candidates
POST   /api/candidates
PATCH  /api/candidates/{id}
POST   /api/candidates/{id}/review
POST   /api/candidates/{id}/ols
POST   /api/candidates/ols
POST   /api/candidates/{id}/match-ols
POST   /api/candidates/{id}/match-local-ontology
POST   /api/candidates/{id}/select-ols-match
POST   /api/candidates/{id}/select-local-match
POST   /api/candidates/{id}/decision
GET    /api/candidates/rejected
POST   /api/candidates/{id}/permanent-reject
POST   /api/candidates/{id}/restore
POST   /api/refine
POST   /api/odk/workflow
GET    /api/exports/approved.robot.tsv
GET    /api/exports/approved.candidates.tsv
```

## OLS Matching

The OLS check uses `httpx` against the public EMBL-EBI OLS4 search API at `https://www.ebi.ac.uk/ols4/api/search`. Matches are stored with the candidate as local JSON metadata:

- matched label
- ontology/source ID
- IRI and short term ID when available
- description
- simple label-similarity confidence score
- a `should_map_existing` recommendation

Curators can select an OLS match in the browser. `Nothing selected` is the default and remains valid; the first OLS result is never automatically selected. Selected matches are included in exports so new ontology terms are not proposed when an existing term is suitable.

## Candidate Rejection

Candidate Curation supports two rejection modes:

- `Temporarily Reject All Visible Candidates` hides the current active queue in the browser session only. These candidates are not permanently rejected and can reappear after refresh or regeneration.
- `Permanently Reject` persists a candidate with status `permanently_rejected`, rejection timestamp, and optional reason. Permanently rejected candidates are excluded from the active queue.

The Permanently Rejected Candidates panel lists rejected records and provides a restore action so they can be curated later.

## Protégé, ROBOT, and ODK Export

Approved candidates can be downloaded from the browser:

- `ROBOT TSV` downloads a ROBOT template-style TSV for ODK workflows.
- `Candidate TSV` downloads a simpler review/export table.

Exports include candidate label, definition, evidence, source document ID, selected OLS match, selected local ontology match, curator decision, and proposed parent/context when available.

For an ODK-managed ontology repository, the safe implementation workflow is:

```powershell
oca odk-apply-approved
oca odk-apply-approved --no-dry-run --production
```

The default command is a dry run: it plans the approved-candidate implementation and blocks validation and upload. The production command:

1. selects only candidates with `approved` or `approved_with_edits` status,
2. writes the ROBOT template under the configured PPO ODK ontology path,
3. runs `OCA_ODK_VALIDATION_COMMAND`,
4. stops without upload if validation fails,
5. uploads through the configured upload mode only after validation succeeds.

Rejected, deferred, new, in-review, and permanently rejected candidates are skipped. Every proposal, review decision, implementation, validation result, and upload attempt is written to `OCA_ODK_AUDIT_LOG_PATH`.

The default template target is:

```text
templates/ai_approved_terms.tsv
```

For Protégé-oriented review, the downloadable TSV can still be used as a curator handoff file or converted through ROBOT into an ontology module according to the target ontology project's template conventions.

## ODK Configuration

The default `.env.example` uses:

```text
OCA_ODK_HOME=C:\Users\ge47vob\ontology-development-kit
```

For a real ontology project, set:

```text
OCA_ONTOLOGY_REPO=C:\path\to\your\odk-managed-ontology
```

The assistant should generate reviewed templates into the ontology repository, then run configured ODK or Make targets.

## LLM Ontology Suggestion Dry Run

Create a traceable LLM ontology-suggestion prompt/export from the canonical Markdown literature repository without credentials:

```powershell
oca llm-ontology-suggestions --dry-run --output .\literature\ontology_suggestions\trace.json
```

The trace includes exported literature records, the prompt, skipped malformed Markdown files, and a schema-valid empty `suggestions` payload. Passing `--no-dry-run` requires configured OpenAI-compatible LLM credentials and validates the response shape before writing the trace. To explicitly reference a generated suggestion trace during the safe ODK handoff:

```powershell
oca odk-apply-approved --suggestion-file .\literature\ontology_suggestions\trace.json
```

## Zotero Metadata

Offline metadata import:

```powershell
oca zotero-import .\zotero-export.json
oca zotero-list
oca zotero-show 1
oca zotero-link-documents .\literature
```

Zotero Web API metadata sync:

```powershell
oca zotero-config
oca zotero-sync --library-type user --library-id 123456 --dry-run
oca zotero-sync --library-type group --library-id 123456 --collection COLLECTIONKEY
```

Configure API sync with `OCA_ZOTERO_LIBRARY_TYPE`, `OCA_ZOTERO_LIBRARY_ID`, optional `OCA_ZOTERO_API_KEY`, optional `OCA_ZOTERO_COLLECTION_KEY`, and `OCA_ZOTERO_API_BASE_URL`. Sync imports metadata only; it does not download attachments or write to Zotero.

The routine browser literature pipeline configuration uses:

- `OCA_ZOTERO_LITERATURE_STORAGE_PATH`: Zotero `storage` folder read by the integrated literature pipeline.

Advanced path settings are available through environment configuration:

- `OCA_ZOTERO_LINKED_ATTACHMENT_BASE_DIR`: optional base folder for relative linked-file attachment paths.
- `OCA_LITERATURE_BASE_DIR`: base folder for the integrated combined literature pipeline, defaulting to `literature`.
- `OCA_LITERATURE_PDF_DIR`: folder where Zotero PDFs are copied before conversion, defaulting to `literature/Paper-PDF`.
- `OCA_LITERATURE_GENERATED_MD_DIR`: folder for full-text Markdown generated from PDFs, defaulting to `literature/Markdown`.
- `OCA_LITERATURE_REPOSITORY_PATH`: per-paper LLM-ready Markdown repository path, defaulting to `literature/papers`.
- `OCA_LITERATURE_COMBINED_OUTPUT_FILE`: final combined LLM-ready Markdown corpus path, defaulting to `literature/combined_literature.md`.
- `OCA_LITERATURE_FUZZY_MIN_SCORE`: minimum title-match score used when merging generated full text into paper Markdown, defaulting to `0.82`.

For the Zotero local API, set `OCA_ZOTERO_API_BASE_URL=http://localhost:23119/api` with the relevant user or group library ID.

Run the integrated configurable pipeline:

```powershell
oca literature pipeline
oca literature pipeline --zotero-storage-dir "C:\Users\<USER>\Zotero\storage" --combined-output-file .\literature\combined_literature.md
```

The pipeline copies PDFs from the configured Zotero literature storage path, converts them to section-structured Markdown with PyMuPDF, creates per-paper repository Markdown records when the import starts from PDFs only, merges matching generated full text into `literature/papers`, and writes the combined LLM-ready Markdown corpus. Passing `--base-dir` to the CLI derives the original expected subfolders (`Paper-PDF`, `Markdown`, `papers`, and `combined_literature.md`) from that base unless a more specific folder option is supplied. The final combined file includes the source folder, file count, document separators, source filenames, and the full merged Markdown content.

## PPO ODK and GitHub Export Configuration

Generated ontology entry artifacts can be staged under the configured PPO ODK ontology directory. The default is:

```text
C:\Users\ge47vob\ontology-development-kit\target\ppo\target\ppo\src\ontology
```

Override it with `PPO_ODK_ONTOLOGY_PATH` or `OCA_PPO_ODK_ONTOLOGY_PATH`. The path is validated before staging generated artifacts.

ODK workflow settings:

- `OCA_ODK_TEMPLATE_RELATIVE_PATH`, default `templates/ai_approved_terms.tsv`
- `OCA_ODK_VALIDATION_COMMAND`, default `make test`
- `OCA_ODK_WORKFLOW_DRY_RUN`, default `true`
- `OCA_ODK_UPLOAD_MODE`, default `github`
- `OCA_ODK_AUDIT_LOG_PATH`, default `logs/odk_workflow_audit.jsonl`

GitHub export helpers read:

- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`, for example `owner/repo`
- `GITHUB_BRANCH`
- `GITHUB_BASE_PATH`, optional target folder inside the repository

Run the entry-generation workflow test with:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_entry_generation.py
```

To incorporate an existing ontology into an ODK-managed project, keep external ontologies as imports or source inputs rather than editing them directly in the project ontology. For PPO, place or reference import sources under the ODK ontology tree, configure ROBOT import/template commands and Makefile targets according to the project conventions, then run the ODK workflow validation before upload. The generated PPO build artifact should be inspected at:

```text
target/ppo/src/ontology/ppo-simple.obo
```

This file represents the ODK-built simplified ontology output after imports, templates, ROBOT commands, and Make targets have been applied. Inspect it with ROBOT, Protégé, or OBO tooling after `make`/ODK validation succeeds.

## Safety Rule

The AI layer may create candidates. It may not create ontology changes. Only human-approved records are eligible for ODK export.
