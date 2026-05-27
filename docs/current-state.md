# Current Project State

Last reviewed: 2026-05-27

## Summary

Ontology Curation Assistant is currently an early working scaffold for a human-in-the-loop ontology curation workflow. The repository already has a FastAPI backend, a Typer command-line interface, SQLAlchemy-backed local persistence, ODK integration helpers, review policy logic, JSON schemas, prompt templates, and tests for the implemented slices.

The main implemented value today is local literature ingestion and inspection, offline Zotero metadata import/linking, metadata-only Zotero Web API sync, structured mockable candidate extraction, candidate persistence for review, plus explicit enforcement of the rule that only human-approved candidates may be exported to ODK-oriented outputs.

## Implemented Capabilities

### Backend API

The FastAPI application is defined in `backend/app/main.py`.

Implemented endpoints:

- `GET /health`: returns service health and app name.
- `GET /api/config`: returns selected runtime configuration, including ODK path status, ontology repository path, and human-approval setting.

The broader review, candidate, export, and audit APIs are documented as planned endpoints in `docs/api.md`, but are not implemented yet.

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

Stored document fields:

- `id`
- `path`
- `filename`
- `suffix`
- `size_bytes`
- `content`
- `created_at`

The larger intended schema is described in `docs/database-schema.md`. Literature sources, extraction runs, and candidate terms now have minimal persistence tables, while richer evidence segmentation, review decisions, audit events, and ODK exports are still planned rather than implemented as database tables.

### Zotero Literature Sources

The current Zotero integration supports both offline imports and metadata-only Web API sync.

Implemented:

- Import from CSL JSON-like Zotero/Better BibTeX exports.
- Import from a Zotero Web-API-like JSON item shape when present in exported files.
- Metadata-only sync from Zotero user or group libraries through the Zotero Web API.
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

Current behavior is preview-only. It can compute the configured export path, but it does not yet write ROBOT templates, run ODK validation, create Git branches, commit files, or open pull requests.

Default configured paths:

- `OCA_ODK_HOME`: `C:\Users\ge47vob\ontology-development-kit`
- Template directory: `src/ontology/templates`
- Default approved-term template: `ai_approved_terms.tsv`

### Ontology Matching

Implemented in `backend/app/ontology/matching.py`:

- Exact label matching against a supplied dictionary of existing ontology terms.

Approximate matching, synonym matching, ontology lookups, and duplicate detection workflows are not implemented yet.

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

Not implemented yet:

- LLM provider integration
- Prompt execution
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
- `OCA_TEMPLATE_DIR`
- `OCA_DEFAULT_TEMPLATE_FILE`
- `OCA_GIT_BRANCH_PREFIX`
- `OCA_REQUIRE_HUMAN_APPROVAL`
- `OCA_LLM_PROVIDER`
- `OCA_LLM_MODEL`
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

Verified on 2026-05-27:

- 37 tests passed.
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

## Known Gaps

The project is not yet a full ontology curation application. The following pieces are documented or scaffolded but not fully implemented:

- Relation persistence tables
- Evidence segment storage
- Zotero attachment ingestion
- Writing changes back to Zotero
- AI/LLM extraction execution
- Candidate review API
- Review UI
- Audit log persistence
- ODK template generation
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
3. Add API endpoints for literature sources, documents, and candidates.
4. Add Zotero attachment discovery/download as a separate metadata-to-file workflow.
5. Implement a real LLM provider behind the structured extraction interface.
6. Add ODK TSV export generation for approved candidates only.
7. Add validation around exported rows and map validation errors back to candidate IDs.
