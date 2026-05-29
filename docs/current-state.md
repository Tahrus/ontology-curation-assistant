# Current Project State

Last reviewed: 2026-05-29

## Summary

Ontology Curation Assistant is currently an early working scaffold for a human-in-the-loop ontology curation workflow. The repository already has a FastAPI backend, a Typer command-line interface, SQLAlchemy-backed local persistence, ODK integration helpers, review policy logic, JSON schemas, prompt templates, and tests for the implemented slices.

The main implemented value today is a local browser workflow for configuration, Zotero metadata sync, local PPO ontology readout, candidate extraction/curation, OLS/local ontology matching, graph visualization, rejection management, and approved-candidate export, plus CLI support for the underlying ingestion and Zotero workflows.

## Implemented Capabilities

### Backend API

The FastAPI application is defined in `backend/app/main.py`.

Implemented endpoints:

- `GET /health`: returns service health and app name.
- `GET /api/config`: returns selected runtime configuration, including ODK path status, ontology repository path, and human-approval setting.
- Browser pages: `/`, `/config`, `/zotero`, `/literature`, `/ontology`, `/curation`, `/export`.
- Browser UI includes client-side route handling for dashboard/header links, a Light/Dark theme toggle persisted in local storage, and a smaller shared logo link back to the dashboard.
- Configuration: `/api/config/status`, `/api/config/zotero`, `/api/config/llm`, `/api/config/ontology-path`, `/api/config/test-zotero`.
- Saved API configurations: `/api/config/saved`, `/api/config/saved/{id}/activate`, and deletion.
- Zotero: `/api/zotero/test`, `/api/zotero/sync`, `/api/zotero/entries`, `/api/zotero/entries/{id}`, `/api/zotero/import-test`.
- Existing ontology: `/api/ontology/status`, `/api/ontology/scan`, `/api/ontology/select-file`, `/api/ontology/index`, `/api/ontology/terms`, `/api/ontology/terms/{term_id}`, `/api/ontology/search`, `/api/ontology/graph`.
- Meta-ontology graph: `/api/meta-ontology/graph`.
- Literature and candidates: `/api/literature`, `/api/extraction/candidates`, `/api/candidates`, `/api/candidates/{id}`, review, OLS matching, local ontology matching, match selection, and decision endpoints. The default active candidate queue includes draft/in-review/deferred/needs-more-evidence records and excludes approved or rejected records.
- Export: `/api/exports/approved.robot.tsv` and `/api/exports/approved.candidates.tsv`.

The broader audit APIs remain planned.

### Command-Line Interface

The CLI entry point is `oca`, configured in `pyproject.toml` and implemented in `backend/app/cli.py`.

Implemented commands:

- `oca doctor`: prints app, database, ODK home, and ontology repository configuration.
- `oca odk-preview`: shows the target path where approved ROBOT templates would be exported.
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
- Browser sync defaults to no limit and follows Zotero pagination until all configured records are fetched.
- Browser literature records are shown by title with author/year/type/DOI/key metadata, an `Open in Zotero` URI when an item key is available, and an expandable JSON section for the corresponding record payload.
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
- PDF attachment sync from Zotero.
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

Current behavior can compute the configured export path and generate downloadable approved-candidate TSV/ROBOT-template TSV from the browser API. It does not yet write directly into an ODK repository, run ODK validation, create Git branches, commit files, or open pull requests.

Default configured paths:

- `OCA_ODK_HOME`: `C:\Users\ge47vob\ontology-development-kit`
- Template directory: `src/ontology/templates`
- Default approved-term template: `ai_approved_terms.tsv`

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
- `OCA_ZOTERO_LIBRARY_TYPE`
- `OCA_ZOTERO_LIBRARY_ID`
- `OCA_ZOTERO_API_KEY`
- `OCA_ZOTERO_COLLECTION_KEY`
- `OCA_ZOTERO_API_BASE_URL`

The project currently includes `.env.example` and a local `.env`.

## Tests

Current test command:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Verified on 2026-05-28:

- 46 tests passed before the current ontology/page split; the focused browser/API suite has 14 tests for the new browser, Zotero, OLS, local ontology, and export behavior.
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
- Static JavaScript regression coverage ensuring `.casefold()` is not used, current routes are present, theme persistence is wired, and literature JSON/Zotero controls are rendered
- Graph endpoint shape for ontology and meta-ontology views

## Known Gaps

The project is not yet a full ontology curation application. The following pieces are documented or scaffolded but not fully implemented:

- Relation persistence tables
- Evidence segment storage
- Zotero attachment ingestion
- Writing changes back to Zotero
- Full production-grade AI/LLM extraction execution and retries
- Audit log persistence
- ODK validation/build execution
- Git branch, commit, and pull request workflow
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
4. Add Zotero attachment discovery/download as a separate metadata-to-file workflow.
5. Harden the OpenAI-compatible LLM provider with retries, model validation, and structured-output support.
6. Add direct ODK repository write/validation actions for approved candidates only.
7. Add validation around exported rows and map validation errors back to candidate IDs.
