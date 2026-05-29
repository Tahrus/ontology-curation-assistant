# Code Overview

Last updated: 2026-05-29

## Application Entry

- `backend/app/main.py` creates the FastAPI app, initializes the runtime schema on startup, mounts `/static`, and serves the browser UI at `/`, `/config`, `/zotero`, `/literature`, `/ontology`, `/curation`, and `/export`.
- `backend/app/api/routes.py` contains the JSON API used by the browser UI.
- `backend/app/static/index.html`, `styles.css`, and `app.js` implement the dependency-light browser workflow.
- The static UI includes a shared top-bar logo, local-storage-backed theme selection, client-side route handling for header/dashboard links, SVG graph rendering, candidate rejection controls, and saved API configuration selection.

## Configuration Flow

- `backend/app/config.py` defines environment-backed settings with the `OCA_` prefix.
- `backend/app/services/runtime_config.py` overlays browser-saved settings from the `app_settings` table and masks secrets in API responses.
- Browser configuration endpoints save Zotero, LLM, and local ontology path values without returning API keys in clear text.
- Saved API configurations are persisted as masked server-side entries in `app_settings`, with active Zotero/LLM configuration IDs.

## Zotero Flow

- `backend/app/zotero/client.py` wraps the Zotero Web API and follows pagination through Link headers.
- `backend/app/zotero/importer.py` normalizes Zotero API or CSL-like records into `LiteratureSource` rows.
- `POST /api/zotero/sync` defaults to no limit and imports all records returned by the configured library or collection.
- `GET /api/zotero/entries` feeds the dedicated Literature/Zotero page. Entry payloads include a Zotero select URI only when the provider item key is valid and unambiguous, and the frontend renders title-first records with metadata and expandable per-record JSON.
- `backend/app/literature/exporter.py` builds the authoritative LLM-ready `literature/literature.json` export from the runtime SQLite cache. The JSON uses schema version `1.0` with a `papers` list, stable `paper_id` values, validated Zotero diagnostics, citation metadata, attachments, labeled sections, full text, LLM-sized chunks, source metadata, and quality flags. It creates the folder automatically and deduplicates by Zotero key, DOI, or source file.
- Browser literature ingestion, test Zotero import, browser Zotero sync, CLI ingest, CLI Zotero import, CLI Zotero link, and CLI Zotero sync refresh the literature JSON export after successful persistence.

## Existing Ontology Flow

- `backend/app/ontology/local.py` scans configured ontology folders and indexes supported files.
- RDF/OWL/Turtle files are parsed with `rdflib`.
- OBO and ROBOT/template TSV files are parsed with simple local readers.
- Indexed term payloads include term ID/IRI, label, definition, synonyms, parents, and source file.
- The browser Existing Ontology page calls `/api/ontology/status`, `/api/ontology/scan`, `/api/ontology/select-file`, `/api/ontology/index`, and term search endpoints.
- `/api/ontology/graph` maps indexed terms to graph nodes and parent/subclass edges.
- `/api/meta-ontology/graph` returns the curation meta-model used by the dashboard graph.

## Candidate Flow

- `backend/app/extraction/service.py` persists validated candidate payloads.
- `backend/app/llm/service.py` provides deterministic mock extraction and an optional OpenAI-compatible chat-completions call.
- Candidate records store curator edits, evidence, selected OLS match, selected local ontology match, lookup statuses, and curator decision.
- The default `/api/candidates` active queue returns only `new`, `in_review`, `needs_more_evidence`, and `deferred` records, so approved and rejected candidates are removed from the curation list after review.
- Candidate records also store permanent rejection timestamp and optional rejection reason.
- Active candidate listing excludes permanently rejected candidates by default.
- Temporary rejection is browser-session-only and hides the visible queue without changing persistent candidate state.
- OLS matching is implemented in `backend/app/ontology/ols.py`.
- Local PPO matching uses `backend/app/ontology/local.py`.
- Neither OLS nor local matches are auto-selected; the UI defaults to `Nothing selected`.
- Graph rendering is defensive: empty graph data displays an empty state, malformed edges are skipped, and node/edge details are shown on click.

## Export Flow

- `backend/app/odk/integration.py` writes approved candidates as ROBOT-template TSV or simple candidate TSV.
- Exports include candidate label, definition, evidence, source document ID, selected OLS match, selected local ontology match, curator decision, mappings, and proposed parent/context.

## Persistence

- SQLAlchemy models live in `backend/app/models/db.py`.
- Runtime schema creation and small SQLite-compatible schema additions live in `backend/app/db/session.py`.
- The project does not yet use Alembic migrations.

## Tests

- Browser/API tests live in `backend/tests/test_browser_api.py`.
- Existing CLI, Zotero, extraction, ODK, and review policy tests remain in `backend/tests/`.
