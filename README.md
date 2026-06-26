# Ontology Curation Assistant

Human-in-the-loop software scaffold for AI-assisted ontology development with ODK-compatible exports.

This project helps ontology developers ingest scientific literature, extract candidate ontology terms and relations, review them with domain experts, and export only approved content into ODK/ROBOT-friendly files.

## Current Status

This is a project scaffold with:

- FastAPI backend structure
- Typer CLI entrypoint
- project management layer for multi-project ontology curation workflows
- standalone `zotero_lit_md` CLI package for Zotero Desktop local-PDF Markdown export
- Docker Compose setup with persistent data/literature/ontology/ODK mounts and ROBOT available in the app image
- SQLite/PostgreSQL-ready settings
- provider-neutral LLM client configuration for Gemini, OpenAI, Anthropic, and custom OpenAI-compatible endpoints
- JSON schemas for candidate terms and relations
- prompt templates for reproducible extraction
- ODK integration configuration through environment variables or Docker mounts
- documentation for architecture, workflow, and ODK integration
- starter tests

See [docs/current-state.md](docs/current-state.md) for a snapshot of what is implemented now versus what is still planned. Developer-oriented notes live in [docs/developer-guide.md](docs/developer-guide.md), [docs/project-structure.md](docs/project-structure.md), [docs/project-ui.md](docs/project-ui.md), [docs/project-ui-fix-notes.md](docs/project-ui-fix-notes.md), [docs/meta-ui.md](docs/meta-ui.md), [docs/literature-project-tags.md](docs/literature-project-tags.md), [docs/active-code-paths.md](docs/active-code-paths.md), [docs/llm-providers.md](docs/llm-providers.md), [docs/ontology-graph.md](docs/ontology-graph.md), [docs/curation-workflow.md](docs/curation-workflow.md), and [docs/odk-workflow.md](docs/odk-workflow.md).

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

## Docker Quick Start

Copy `.env.example` to `.env` if you want local overrides, then run:

```powershell
docker compose up --build
```

The browser UI is served at <http://127.0.0.1:8000/>. Compose mounts persistent runtime data under `/data`, local `literature/` at `/data/literature`, `ontology/` at `/ontology`, and `odk-workspace/` at `/odk`. Put or mount an ODK-managed ontology checkout under `odk-workspace/ontology` when ODK/ROBOT workflows should operate on it.

The image installs Java, `make`, `git`, and a `robot` command wrapper. Check container diagnostics from Configuration > Docker / ODK Diagnostics or with:

```powershell
docker compose run --rm api robot --version
docker compose run --rm api python -m pytest
```

Inside the Linux container, use POSIX paths such as `/ontology`, `/odk/ontology`, and `/data/literature`; Windows host paths are supplied through Compose volume mounts, not hard-coded into app settings.

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

- Project Dashboard: active project metadata, local status, project hierarchy tree, and links to the main workflows.
- Project Management: wizard-style create/edit/select flow, clear project cards, detail/next-step guidance, active project selection, hierarchy metadata, workspace/repository paths, and optional path statuses.
- Settings: Zotero metadata sync settings, LLM provider/model settings, LLM connection testing, Docker/ODK diagnostics, Zotero connection testing, Zotero metadata sync, and the local Zotero literature source path used for PDF import.
- Literature: two clear, mutually exclusive sub-tabs for `Curated Literature` and `New / Uncurated Literature`, each with search/status filtering, canonical project-tag filtering, metadata/Markdown/source provenance display, and open/review/edit actions for staged or curated entries.
- Ontology: local PPO ontology path, detected ontology files, indexing, term search, and a collapsible parent-child ontology tree.
- Curate Prompts: create, edit, version, duplicate/archive, and preview ontology suggestion prompt templates stored as Markdown files with YAML front matter.
- Ontology Suggestions: read-only project-scoped LLM analysis over selected literature and selected ontology context, with prompt template selection, rich cheap function-test diagnostics, token/cost estimates, run logs, and human review before candidates enter the curation queue.
- Curation: document ingestion, candidate extraction, candidate editing, local PPO matching, and external OLS matching.
- Suggestions: project-scoped curation runs, structured suggestion import, and rich expert review decisions.
- Evaluation: project-scoped metrics and curation-run comparison.
- Export / ODK: approved candidate downloads for ROBOT/ODK/Protégé-oriented workflows.

The header includes a consistent logo link back to the Dashboard, persistent active-project banner, and a Light/Dark theme toggle. Theme choice is stored in browser local storage; if no choice exists, the UI follows the system color-scheme preference. Header and dashboard navigation use the static app's current client-side route map, so switching pages updates the visible workflow immediately without requiring a browser refresh.
Startup loads the dashboard status first and then only the current page's data, so an optional workflow error such as an unparsable selected ontology file is shown as a visible message instead of leaving the local workspace loading indicator in place.
Buttons, links, and other clickable controls provide visible pressed feedback plus an accessible status toast. Long-running actions disable their button, show a running label immediately, and report completion or errors in text.

The workflow supports:

- create, edit, and select active ontology curation projects with project type, parent/child hierarchy, ontology ID/prefix, minimal scope notes, optional ontology/literature/ODK/Git paths, local folder layout, GitHub metadata, existing ontology project nodes, and optional AI-assisted metadata drafts that fill empty fields without creating the project automatically
- review backend, database, Zotero, and LLM readiness in Application Status
- save Zotero credentials and LLM/chatbot credentials in Configuration
- test Zotero credentials, sync all configured Zotero records, load local test Zotero entries, or import local Zotero PDFs into Markdown
- view synced/imported Zotero records, open them in Zotero when an item key is available, inspect raw/clean/LLM-context Markdown, and review metadata title matches, document state, extraction quality, document role, warnings, and automatic-extraction inclusion
- inspect ontology source status from the active project, preferring its built/released ontology file and then its editable ontology file without silently falling back to global/demo ontology paths
- inspect ontology classes in a searchable collapsible tree and inspect the curation meta-model graph
- create project curation runs with `literature_only`, `ontology_only`, `literature_plus_ontology`, or `structured_relation_extraction` prompt strategies
- parse structured JSON suggestions into persistent project/run records while preserving malformed raw output diagnostics
- review each suggestion as accepted, edited, rejected, duplicate, unsupported, or further_review with comments and review time
- compute project evaluation metrics for precision, unsupported rate, duplicate rate, relation correctness, evidence traceability, and review effort
- compare curation runs by exact label overlap, normalized label overlap, and relation triple overlap
- ingest a server-side literature file path or paste extracted text/notes into the Literature panel
- extract candidates from all valid LLM-ready literature Markdown files in the repository without selecting an individual paper
- run deterministic mock extraction, or use a configured Gemini, OpenAI, Anthropic, or custom OpenAI-compatible LLM
- run read-only ontology suggestion tests and single/multi-paper suggestion analyses without modifying literature, ontology files, ODK templates, GitHub state, or project tags
- create candidates manually or generate a draft candidate from a curator nudge
- edit labels, definitions, rationales, source evidence, synonyms, parents, and mappings
- compare candidates against local PPO terms and external EMBL-EBI OLS terms
- approve, reject, defer, or mark candidates as needing more evidence
- intentionally select an existing local/OLS match or leave `Nothing selected`
- export approved candidates as `approved_candidates.robot.tsv` or `approved_candidates.tsv`

The UI calls JSON endpoints under `/api/...`, so CLI-created candidates and browser-edited candidates use the same SQLite database.
Credentials entered in the UI are stored in the local SQLite database for development use and are masked in API responses.
Saved Zotero, LLM, and Elsevier publisher API configurations are listed on the Configuration page with provider/library/model metadata, masked secrets, timestamps, and active-state controls.

Literature import, ingestion, linking, and Zotero sync workflows refresh the LLM-ready literature repository at:

```text
literature/papers
```

The folder is created automatically when needed. Each imported paper is saved as a separate canonical `.md` file with YAML front matter for stable metadata (`paper_id`, Zotero key/item key, PDF path/hash, title/authors/year/DOI, detected title/DOI, DOI/title match status, extraction engine attempts, extraction quality, document state, document role, warnings, and extraction inclusion flags), followed by human-readable Markdown sections for abstract, notes, and ontology-relevant extracted content. Filenames are deterministic and filesystem-safe, preferring DOI, PMID, stable literature ID, or a title-derived slug with a short digest.

The SQLite tables are runtime cache and workflow state. Literature content handed to an LLM is loaded from the Markdown repository, validated, filtered, combined into a single Markdown corpus headed `# Literature Corpus`, and separated by literature entry ID and source filename. The Literature page shows Markdown-oriented records and metadata for human review instead of exposing raw JSON.

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

The per-paper repository omits page-wise chunks, running headers/footers, page numbers, references, and publisher boilerplate where the local deterministic cleaner can identify them. Candidate extraction uses only records in the `ready_for_llm` state with usable extraction quality and appropriate domain/review roles. Records marked `metadata_mismatch`, `incomplete`, `blocked`, `needs_review`, `requires_manual_review`, `failed`, `methodology_article`, or `supplementary_information` are excluded from automatic domain extraction unless a curator updates the review metadata. Malformed Markdown files are reported and skipped when at least one valid file is available; if none are valid, the UI asks you to import literature first. The extraction API also supports `dry_run: true` to report included and excluded repository files plus estimated context size without extracting candidates. Reset the literature workspace from the Literature page with explicit confirmation, or from the CLI:

```powershell
oca literature reset-repository --yes
```

The reset clears every file and subfolder under the configured `OCA_LITERATURE_BASE_DIR` literature directory, recreates the empty directory, and clears the runtime literature/candidate cache. It refuses unsafe reset targets such as filesystem roots and unlinks symlinks instead of following them.

The literature repository is project-scoped and explicitly two-stage. Configure Zotero/local import paths under Settings, select an active project, then use Literature > Import literature. Import creates pipeline-generated staged entries only. Review metadata and Markdown, assign project tags, and promote an entry before downstream candidate extraction or ontology curation can use it. Zotero sync compares current Zotero records against staged and curated project literature and imports only new entries using stable identifiers in priority order: DOI, PII, PMID/PMCID, arXiv ID, ISBN, ISSN+title, URL, then normalized title+year. Equivalent CLI commands are:

```powershell
oca literature import --project protein-precipitation --doi 10.1016/j.example.2026.100001
oca literature import --project protein-precipitation --pii S0098135425001978
oca literature test-api --project protein-precipitation --pii S0098135425001978
# Explicit opt-in fallback only:
oca literature import --project protein-precipitation --doi 10.1016/j.example.2026.100001 --pdf .\paper.pdf --allow-pdf-fallback
# Explicit PDF-only/debug mode only:
oca literature import --project protein-precipitation --pdf-dir .\pdfs --extraction-mode pdf_only
oca literature list --project protein-precipitation
oca literature staged list --project protein-precipitation
oca literature promote <canonical-id> --project protein-precipitation --project-tag protein-precipitation
oca literature curated list --project protein-precipitation
oca literature cleanup-staged --project protein-precipitation --only-unpromoted --dry-run
oca literature cleanup-staged --project protein-precipitation --only-unpromoted --yes
oca literature deduplicate --project protein-precipitation --dry-run
oca literature deduplicate --project protein-precipitation --apply
oca literature build-combined --project protein-precipitation
oca literature migrate-old --project protein-precipitation --dry-run
oca literature migrate-old --project protein-precipitation --apply
oca literature reset --project protein-precipitation --yes
```

The implementation adapted from `literatur_test_2` now lives in `backend/app/literature/canonical.py`; OCA never imports the external test directory at runtime. It normalizes DOI and PII, prefers PII for canonical names, uses exact normalized titles to bridge DOI-only and PII-only imports, and preserves curation fields on re-import. The default extraction mode is `publisher_api_required`: Zotero supplies identifiers and metadata, then structured full-text providers are tried before any Markdown is generated. The working Elsevier Article Retrieval path is preserved through `backend/app/literature/providers/elsevier_provider.py`, which delegates to the existing XML retriever/parser. Publisher/source lookup keeps Elsevier first and includes scaffolded adapters for arXiv, PMC/PubMed, Springer, Wiley, Crossref, generic HTML, and explicit PDF fallback. Elsevier Article Retrieval currently supports only PII and DOI, so other identifiers are retained and recorded as unsupported rather than being sent to invented endpoints. A PII-specific 400/404, invalid XML, or missing full-text response can advance to DOI; unavailable structured full text creates a blocked metadata-only staged entry that asks for manual structured Markdown instead of silently reading PDFs. Structured XML is saved and converted locally to the staged review Markdown; the converter retains the abstract, nested sections, equations represented as text, figure captions, tables, appendices/back matter, and references. Failed identifier attempts remain visible and never silently invoke the PDF extractor. PyMuPDF remains available only through `pdf_fallback_allowed` (or `--allow-pdf-fallback`) and the diagnostic `pdf_only` mode. `backend/app/literature/pipeline.py` is a backwards-compatible wrapper that obeys the same mode; `BibPipelineCombined.py` is legacy and is not called by the default path.

The default literature artefacts are:

```text
projects/<project_slug>/literature/
  sources/                   staged source copies; original Zotero data is untouched
  markdown/                  pipeline-generated staged Markdown
  metadata/                  staged metadata, source reports, validation reports, provenance, and promotion status
  fallback/                  lower-priority PDF Markdown retained after explicit fallback
  api_tests/                 isolated XML/Markdown from publisher API diagnostics
  curated/
    markdown/                human-reviewed authoritative Markdown
    metadata/                reviewed metadata, project tags, and staged traceability
  combined_literature.md     generated from curated entries only
  backups/                   deduplication and migration backups
  archive/                   archived legacy files
```

LLM-facing Markdown contains no YAML front matter. It begins with one title, one normalized PII line when available, one optional normalized DOI line, then the paper content. Rich provenance and human fields remain in JSON metadata. New imports register repository-relative artifact paths, artifact types, staged/curated ownership, `literature_type`, `metadata_source`, `content_source`, `extraction_mode`, API status/errors, `attempted_providers`, `selected_provider`, `fulltext_status`, `markdown_status`, `source_quality`, metadata/Markdown quality reports, `api_identifier_used_kind`, `api_identifier_used_value`, ordered `api_identifier_attempts`, `api_retrieval_source`, lookup identifiers, `xml_retrieved`, `pdf_used`, `fallback_used`, fallback authorization, warnings, XML/PDF Markdown artifact paths, and manual/canonical Markdown validation paths when applicable. Metadata resolution prefers complete Zotero fields, fills Elsevier records from XML, and can use Crossref metadata for metadata-only entries. Books and book chapters are first-class literature entries with `literature_type` values such as `book`, `book_chapter`, `conference_paper`, and `report`; ISBN, DOI, URL, title/creator/year, and Zotero book fields are retained. ACS DOI imports do not scrape ACS or parse Crossref PDF links automatically; if no structured XML/TDM link is available, OCA creates a metadata-only staged entry with `fulltext_status: structured_fulltext_unavailable` or `pdf_available_but_not_used` and `markdown_status: manual_markdown_required`. Manual Markdown can be uploaded and validated for a staged metadata-only entry; valid manual Markdown becomes the canonical staged Markdown that can be promoted, while invalid Markdown remains blocked with validation errors. Existing single-stage canonical entries remain in place and are treated conservatively as staged/needs-review; OCA does not guess that they were manually curated. Promotion stores a trace back to the staged metadata.

On Literature, **Delete uncurated imported literature and generated files** first previews and then, after confirmation, removes unpromoted artifacts from the active project repository and from a distinct configured legacy global literature repository. The bounded orphan scan covers OCA-managed `sources`, `markdown`/`Markdown`, `metadata`, `raw`, `clean`, `context`, `reports`, `papers`, `blocked`, `combined`, `fallback`, `raw_markdown`, `clean_markdown`, `llm_context`, `metadata_reports`, `rejected_or_review_required`, and `Paper-PDF` folders. Old untracked files in those locations are conservatively classified as generated staged artifacts. Curated artifacts, promoted staging records, project/ontology/settings files, and original external Zotero storage are protected. `combined_literature.md` is removed when no curated entries exist and rebuilt from curated entries otherwise. The CLI `--dry-run` command above previews the selected project repository without deleting files.

### Zotero from the Browser

In Configuration > Zotero Metadata Sync, enter:

- Zotero library type: `user` or `group`
- Zotero user ID or group ID
- Zotero API key, if needed for the target library
- optional collection key
- API base URL, using `http://127.0.0.1:23119/api` with library type `user`, library ID `0`, and no API key for Zotero Desktop's local API

Use Zotero Connection to test the credentials, then click `Sync All Zotero Records`. The browser sync defaults to no limit and follows Zotero pagination until all records in the configured library or collection are retrieved. An advanced optional limit is available only for testing. Sync refreshes the Markdown files in `literature/papers`.
The Zotero Metadata Sync controls are bound after the DOM is ready and use stable field IDs. If a required panel element is missing, the UI shows a reload message instead of throwing a null-selector error.

If you do not have real Zotero credentials ready, click `Load Test Entries`; this imports two local bibliography records that are enough to test selection and mock extraction.

The Literature page contains the import action, imported-literature review queue, curated-literature editor, promotion controls, project-tag selector, and confirmed unpromoted-stage cleanup. Literature/Zotero paths and publisher settings now live under Settings.

Publisher settings support `ELSEVIER_API_KEY`/`OCA_ELSEVIER_API_KEY`, optional `ELSEVIER_INSTTOKEN`/`OCA_ELSEVIER_INST_TOKEN`, `OCA_ELSEVIER_API_BASE_URL` (default `https://api.elsevier.com`), plus stored Settings fields for Springer Nature API key, Wiley TDM token, Crossref contact email, NCBI contact email/API key, and OpenAlex email. `OCA_PUBLISHER_API_ENRICHMENT_ENABLED` and `OCA_LITERATURE_EXTRACTION_MODE` (default `publisher_api_required`) still control the active import mode. Missing values load safely; saved values are merged without changing unrelated settings. Environment secrets take precedence over values stored through Settings, and API responses expose only configured/missing status. Saving publisher settings creates or updates an `Elsevier Publisher API` entry under Saved API Configurations; secrets remain masked, and the saved entry can be activated through the existing controls. Settings offers `publisher_api_required`, `pdf_fallback_allowed`, and `pdf_only`; PDF use is never inferred. Use the API test controls (or `oca literature test-api`) to retrieve and parse XML into isolated `api_tests/` artifacts without reading a PDF or creating a staged entry. The Settings diagnostics panel reports the selected mode, provider credential status, Elsevier/Zotero configuration, whether fallback is enabled, and the last import result. Staged review cards display literature type, metadata/Markdown quality, content/metadata source, API status, the identifier used and ordered attempts, XML/PDF use, fallback authorization, and warnings.

### LLM / Chatbot Configuration

In API Key Configuration, select:

- provider: `gemini`, `openai`, `anthropic`, or `openai-compatible`
- model from the dropdown, or a manual model override
- API key, or an API key environment variable such as `GEMINI_API_KEY`
- optional base URL for custom/OpenAI-compatible endpoints
- temperature, max output tokens, timeout, retry count, streaming preference, and optional context character limit through `OCA_LLM_CONTEXT_CHAR_LIMIT`

Provider presets supply default model, model list, base URL where applicable, default API key environment variable, timeout, retry count, temperature, and max output tokens. Current defaults are:

- Gemini: `gemini-2.5-flash`, env vars `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- OpenAI: `gpt-4.1-mini`, env var `OPENAI_API_KEY`
- Anthropic: `claude-3-5-sonnet-latest`, env var `ANTHROPIC_API_KEY`
- Custom/OpenAI-compatible: manual base URL, model, and key/env-var

For Gemini in Docker, set:

```powershell
$env:GEMINI_API_KEY="your-key"
$env:OCA_LLM_API_KEY_ENV_VAR="GEMINI_API_KEY"
docker compose up --build
```

Use `Test LLM connection` in the UI or `oca llm-test` from the CLI. The test sends a tiny prompt and reports provider, canonical provider key, model, API key presence/source, latency, status, and a short response or actionable error. API keys are masked in responses and logs. Provider labels and aliases such as `Gemini API`, `Google Gemini`, `google_gemini`, `google-ai`, and `google_ai` are normalized to the canonical `gemini` provider before saving, activating saved configs, and making real LLM calls.

If no LLM key is configured, Candidate Extraction still works through a deterministic mock extractor. Select `Use configured LLM` only when you want the backend to call the configured provider.

### Candidate Extraction and Curation

Add optional guidance, then click `Extract Candidates`. The backend combines all valid LLM-ready Markdown files in the configured literature repository automatically. Draft, in-review, deferred, and needs-more-evidence candidates appear in Candidate Curation, where you can edit all curator-facing fields, add a manual candidate, approve/reject candidates, and run OLS checks. The Candidate Curation page also includes a graph-assisted ontology context panel. Select a candidate and an ontology node to set the proposed parent class, relation source, relation target, duplicate target, or comparison note. Proposed semantic relations are stored in the candidate's graph-review proposal data and previewed as dashed graph edges; this does not mutate the ontology directly. Approved and rejected candidates leave the active curation queue. Use `Run OLS For Draft Candidates` to batch-check draft candidates.

Use Curate Prompts at <http://127.0.0.1:8000/curate-prompts> for ontology-suggestion prompt template management. The legacy curation-suggestion API still assembles its saved prompt deterministically with the selected existing ontology `.obo` file and the current `literature/combined_literature.md` file; missing or empty literature, missing LLM credentials, or a missing/non-OBO selected ontology file stops the request before any LLM call. Request traces and parsed responses are written under `literature/curation_runs/`; invalid JSON responses are preserved as raw text for debugging. The selected OBO file is read-only during suggestion generation.

### Existing PPO Ontology

Open <http://127.0.0.1:8000/ontology> to inspect the ontology connected to the active project. If no project is active, the page asks you to select or create one first. The active project determines the editable ontology file path, built/released ontology file path, ODK repository path, ontology ID/prefix, and base IRI shown on the page.

The project ontology source supports:

- `.owl`, `.rdf`, `.ttl`
- `.obo`
- ROBOT/template `.tsv`

The page prefers the active project's existing built/released ontology file, then its existing editable ontology file. If neither exists, it shows a warning instead of falling back to a global or previously selected ontology. The app extracts term IDs/IRIs, labels, definitions, synonyms, parent IDs when available, and source file metadata. This is local readout only; Protégé is not required.

The ontology page defaults to a focused, top-down SVG taxonomy browser rather than rendering the whole ontology at once. Terms are positioned only from asserted `is_a`/subclass relationships: parent classes are above subclasses, children are below parents, and siblings are arranged horizontally. The initial overview shows a small top-level section with a shallow depth. Branches can be expanded or collapsed, hidden child counts are shown on collapsed or depth-limited nodes, node labels can be hidden for crowded views, and clicking a node visibly highlights it, de-emphasizes unrelated visible nodes, and shows label, identifier/IRI, definition, synonyms, superclasses, direct subclasses, semantic relations, source/evidence, and status when available. Use the graph search box to search by label, ID, synonym, or relation source/target, then jump into focus mode for that class. Focus mode shows the selected class, its superclass path, configurable descendant depth, and directly connected semantic relation endpoints when available. The view can be reset to the top-level overview, zoomed, panned, fit to screen, or centered on the selected node. Non-hierarchical semantic relations are drawn afterward as dashed side links for the visible/focused section, so they do not change the class hierarchy layout. The older graph endpoint remains available for compatibility, but the circular graph is no longer the default ontology visualization. The Dashboard shows project hierarchy tiles instead of a meta-ontology graph.

Relation type options for graph-assisted review come from `GET /api/ontology/relation-types`. The initial catalogue includes common ontology relations such as `has input`, `has output`, `has participant`, `has part`, `part of`, `is measurement of`, `has measurement datum`, `has quality`, `has process parameter`, and `has unit`, with IDs, inverse labels, descriptions, and simple source/target expectations where available.

Local PPO matching differs from OLS matching:

- Local PPO matching checks candidates against the ontology file selected on the Existing Ontology page.
- OLS matching checks external EMBL-EBI OLS results.
- Both default to `Nothing selected`; no first result is automatically selected.
- Leaving `Nothing selected` means no existing term has been chosen yet, and the candidate still needs curator review or can be explicitly marked `propose_new_term`.

Useful endpoints include:

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/suggest-base-iri
POST   /api/projects/suggest-metadata
GET    /api/projects/active
GET    /api/projects/{project_ref}
PATCH  /api/projects/{project_ref}
POST   /api/projects/{project_ref}/select
POST   /api/projects/{project_ref}/activate
GET    /api/projects/{project_ref}/children
GET    /api/projects/{project_ref}/odk/validate
GET    /api/projects/{project_ref}/odk/logs
POST   /api/projects/{project_ref}/odk/logs
GET    /api/projects/{project_ref}/exports/accepted.robot.tsv
GET    /api/config/status
POST   /api/config/zotero
POST   /api/config/llm
POST   /api/config/ontology-path
POST   /api/config/literature
GET    /api/curation/prompt
POST   /api/curation/prompt
DELETE /api/curation/prompt
GET    /api/curation/prompt-strategies
GET    /api/curation/runs
POST   /api/curation/runs
POST   /api/curation/runs/{run_id}/suggestions
GET    /api/suggestions
POST   /api/suggestions/{suggestion_id}/review
POST   /api/evaluation/compute
POST   /api/evaluation/compare
GET    /api/config/saved
POST   /api/config/saved
POST   /api/config/saved/{id}/activate
DELETE /api/config/saved/{id}
POST   /api/config/test-zotero
POST   /api/zotero/test
POST   /api/zotero/sync
GET    /api/zotero/entries
GET    /api/zotero/entries/{id}
PATCH  /api/zotero/entries/{id}/project-tags
POST   /api/zotero/import-test
GET    /api/ontology/status
POST   /api/ontology/scan
POST   /api/ontology/select-file
POST   /api/ontology/index
GET    /api/ontology/terms
GET    /api/ontology/terms/{term_id}
GET    /api/ontology/search?q=...
GET    /api/ontology/graph
GET    /api/ontology/tree
GET    /api/ontology/relation-types
GET    /api/meta-ontology/graph
GET    /api/literature
POST   /api/literature
POST   /api/literature/pipeline/run
PATCH  /api/literature/repository/review
GET    /api/literature/doctor
GET    /api/literature/repository/report
POST   /api/literature/context/build
POST   /api/literature/repository/retry-extraction
POST   /api/literature/repository/regenerate-clean
POST   /api/literature/repository/regenerate-context
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

## Project-Based Workflow

Create a project from the browser at <http://127.0.0.1:8000/projects>, or from the CLI:

```powershell
oca project create --name "Protein precipitation" --ontology-id ppo --ontology-title "Protein Precipitation Ontology" --base-iri "http://purl.obolibrary.org/obo/PPO_" --local-workspace-path "C:\path\to\workspace" --github-url "https://github.com/example/ppo"
oca project list
oca project select protein-precipitation
oca project show
```

Project creation writes a clear local layout under `projects/<project_slug>/` with `literature/`, `ontology/`, `curation/`, `evaluation/`, and `logs/` subfolders plus `project.json`. Existing non-project literature, candidate, and export workflows remain available.

The browser Projects page now uses a wizard-style project-management scaffold for root, child/domain, module, application, and existing-ontology projects. Project records can store project type, parent project, namespace/prefix, base IRI, short description, minimal scope notes, optional ODK/editable/built/literature/local-Git paths, and GitHub metadata. Optional missing paths are shown as warnings/statuses and do not block conceptual project creation. Dependency/import placeholders and external-reference placeholders are intentionally not part of this UI; actual ontology import/dependency handling will be solved later during curation and ontology review. See [docs/project-structure.md](docs/project-structure.md).

Run read-only ontology suggestions from the browser at <http://127.0.0.1:8000/ontology-suggestions>, or from the CLI:

```powershell
oca suggestions prompts
oca suggestions test --project protein-precipitation --prompt conservative_term_suggestions
oca suggestions test-api --project protein-precipitation --prompt conservative_term_suggestions
oca suggestions run --project protein-precipitation --literature-item <canonical-id> --prompt conservative_term_suggestions
oca suggestions list-runs
oca suggestions show-run <run-id>
```

Suggestion workflow files are stored separately from the literature pipeline under `data/ontology_suggestions/{prompts,runs,logs}`. Prompt templates live as one Markdown file with YAML front matter per template under `data/ontology_suggestions/prompts/`. The cheap API function test sends only a minimal strict-JSON request, can recover whole-response Markdown-fenced JSON with explicit diagnostics, and records diagnostics under `data/ontology_suggestions/logs/api_function_tests/`. Real runs require explicit literature selection, default to one selected paper, default ontology context to labels plus definitions plus existing relations, validate strict JSON before storage, record prompt template ID/title/version, and keep malformed raw responses in the run directory. Accepting or editing an ontology suggestion creates a normal candidate for human curation; it never writes ontology files directly.

Create a curation run and import structured LLM suggestion JSON:

```powershell
oca curation run --project protein-precipitation --strategy literature_plus_ontology --raw-output-file .\suggestions.json
oca curation list-runs --project protein-precipitation
oca curation review 1 --status edited --reviewer "Curator" --comment "Accepted after wording edit" --review-time-seconds 120
```

Review statuses are `accepted`, `edited`, `rejected`, `duplicate`, `unsupported`, and `further_review`. Default project exports include only accepted and edited suggestions:

```powershell
oca ontology export-templates --project protein-precipitation
```

Compute and compare evaluation metrics:

```powershell
oca evaluation compute --project protein-precipitation
oca evaluation compare --project protein-precipitation --runs 1 --runs 2
oca evaluation export --project protein-precipitation --output .\evaluation.json
```

Project ODK support currently validates/logs project metadata and required paths, initializes a project ODK folder placeholder, and exports accepted/edited suggestions. Build/test commands are logged as explicit pending manual operations until safe command execution is configured for the project:

```powershell
oca ontology init-odk --project protein-precipitation
oca ontology validate --project protein-precipitation
oca ontology build --project protein-precipitation
oca ontology test --project protein-precipitation
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
OCA_ODK_HOME=/odk
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

The trace includes exported literature records, the prompt, skipped malformed Markdown files, and a schema-valid empty `suggestions` payload. Passing `--no-dry-run` requires configured provider-neutral LLM credentials and validates the response shape before writing the trace. To explicitly reference a generated suggestion trace during the safe ODK handoff:

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

The no-project compatibility pipeline can still read:

- `OCA_ZOTERO_LITERATURE_STORAGE_PATH`: Zotero `storage` folder read by the integrated literature pipeline.

The following paths are legacy/global compatibility settings; active-project imports derive `sources`, `markdown`, `metadata`, and `combined_literature.md` from the project's literature repository:

- `OCA_ZOTERO_LINKED_ATTACHMENT_BASE_DIR`: optional base folder for relative linked-file attachment paths.
- `OCA_LITERATURE_BASE_DIR`: base folder for the integrated combined literature pipeline, defaulting to `literature`.
- `OCA_LITERATURE_PDF_DIR`: folder where Zotero PDFs are copied before conversion, defaulting to `literature/Paper-PDF`.
- `OCA_LITERATURE_GENERATED_MD_DIR`: folder for full-text Markdown generated from PDFs, defaulting to `literature/Markdown`.
- `OCA_LITERATURE_REPOSITORY_PATH`: per-paper LLM-ready Markdown repository path, defaulting to `literature/papers`.
- `OCA_LITERATURE_COMBINED_OUTPUT_FILE`: final combined LLM-ready Markdown corpus path, defaulting to `literature/combined_literature.md`.
- `OCA_LITERATURE_FUZZY_MIN_SCORE`: minimum title-match score used when merging generated full text into paper Markdown, defaulting to `0.82`.

For the Zotero local API, set `OCA_ZOTERO_API_BASE_URL=http://localhost:23119/api` with the relevant user or group library ID.

The legacy command name remains routed to the canonical implementation:

```powershell
oca literature pipeline
oca literature pipeline --zotero-storage-dir "C:\Users\<USER>\Zotero\storage" --combined-output-file .\literature\combined_literature.md
```

Prefer `oca literature import --project ...`; `oca literature pipeline` is retained only for command compatibility and now writes the canonical layout rather than invoking `BibPipelineCombined`.

Later BFO support should target BFO 2020 terminology and identifiers. Later relation validation should use a version-controlled static YAML or JSON relation catalogue in this repository, with optional checks against ontology imports.

## PPO ODK and GitHub Export Configuration

Generated ontology entry artifacts can be staged under the configured PPO ODK ontology directory. The Docker-oriented default is:

```text
/odk/ontology/src/ontology
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
