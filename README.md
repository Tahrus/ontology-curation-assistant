# Ontology Curation Assistant

Human-in-the-loop software scaffold for AI-assisted ontology development with ODK-compatible exports.

This project helps ontology developers ingest scientific literature, extract candidate ontology terms and relations, review them with domain experts, and export only approved content into ODK/ROBOT-friendly files.

## Current Status

This is a project scaffold with:

- FastAPI backend structure
- Typer CLI entrypoint
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

## Browser Workflow

The browser UI is split into small pages:

- Dashboard: local status and links to the main workflows.
- Configuration: Zotero API settings, LLM/chatbot settings, Zotero connection testing, and Zotero sync.
- Literature: searchable list of imported or synced Zotero records with titles, Zotero links, and per-record JSON inspection.
- Existing Ontology: local PPO ontology path, detected ontology files, indexing, and term search.
- Curation: document ingestion, candidate extraction, candidate editing, local PPO matching, and external OLS matching.
- Export: approved candidate downloads for ROBOT/ODK/Protégé-oriented workflows.

The header includes a small consistent logo link back to the Dashboard and a Light/Dark theme toggle. Theme choice is stored in browser local storage; if no choice exists, the UI follows the system color-scheme preference. Header and dashboard navigation use the static app's current client-side route map, so switching pages updates the visible workflow immediately without requiring a browser refresh.

The workflow supports:

- review backend, database, Zotero, and LLM readiness in Application Status
- save Zotero credentials and LLM/chatbot credentials in Configuration
- test Zotero credentials, sync all configured Zotero records, or load local test Zotero entries
- view and select synced/imported Zotero records as source material, open them in Zotero when an item key is available, and inspect the record JSON used by the UI
- scan and index a local PPO ontology folder, defaulting to `C:\Users\ge47vob\ontology-development-kit\target\ppo`
- inspect ontology and curation meta-model graphs with pan, zoom, node selection, and edge selection
- ingest a server-side literature file path or paste extracted text/notes into the Literature panel
- select a Zotero entry or ingested document for candidate extraction
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

### Zotero from the Browser

In API Key Configuration, enter:

- Zotero library type: `user` or `group`
- Zotero user ID or group ID
- Zotero API key, if needed for the target library
- optional collection key

Use Zotero Connection to test the credentials, then click `Sync All Zotero Records`. The browser sync defaults to no limit and follows Zotero pagination until all records in the configured library or collection are retrieved. An advanced optional limit is available only for testing.

If you do not have real Zotero credentials ready, click `Load Test Entries`; this imports two local bibliography records that are enough to test selection and mock extraction.

### LLM / Chatbot Configuration

In API Key Configuration, enter:

- provider: `openai` or `openai-compatible`
- API key
- optional model name, such as `gpt-4o-mini`
- optional OpenAI-compatible base URL

If no LLM key is configured, Candidate Extraction still works through a deterministic mock extractor. Select `Use configured LLM` only when you want the backend to call the configured OpenAI-compatible chat completions endpoint.

### Candidate Extraction and Curation

Select a Zotero entry or ingested document, add optional guidance, then click `Extract Candidates`. Draft, in-review, deferred, and needs-more-evidence candidates appear in Candidate Curation, where you can edit all curator-facing fields, add a manual candidate, approve/reject candidates, and run OLS checks. Approved and rejected candidates leave the active curation queue. Use `Run OLS For Draft Candidates` to batch-check draft candidates.

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

The ontology page also includes a graph view. Terms are nodes and parent/subclass relationships are edges. Use mouse wheel zoom, drag pan, and click nodes or edges for details. The Dashboard includes a compact meta-ontology graph showing how sources, evidence, candidates, matches, decisions, and exports relate.

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

For an ODK-managed ontology repository, copy or move the ROBOT TSV into the configured template directory, typically:

```text
src/ontology/templates/ai_approved_terms.tsv
```

Then process it with the ontology project's normal ODK/ROBOT workflow. For Protégé-oriented review, use the TSV as a curator handoff file or convert it through ROBOT into an ontology module according to the target ontology project's template conventions.

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

## Safety Rule

The AI layer may create candidates. It may not create ontology changes. Only human-approved records are eligible for ODK export.
