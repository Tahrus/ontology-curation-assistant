# ODK Workflow and Code Overview

Last reviewed: 2026-05-27

This document describes what the Ontology Curation Assistant (OCA) code currently does, how it is connected to ODK, and which parts of the intended workflow are still planned. It is based on the current source tree, tests, configuration, and documentation.

## 1. Project Purpose

Ontology Curation Assistant is a human-in-the-loop scaffold for AI-assisted ontology curation. Its intended role is to:

1. ingest scientific literature,
2. extract candidate ontology terms from source text,
3. preserve evidence and extraction provenance,
4. let human curators review candidate terms,
5. export only approved candidates into ODK/ROBOT-compatible files,
6. validate and submit those changes through the normal ontology development workflow.

The central safety boundary is that AI-generated candidates are suggestions only. They must not directly modify the ontology. Only human-approved candidates should be eligible for ODK export.

## 2. Current Implementation Status

| Area | Implemented now | Still planned |
| --- | --- | --- |
| CLI | Typer commands for config inspection, ingestion, literature display, structured mock extraction, candidate display, Zotero metadata import/sync, Zotero linking, and ODK path preview. | Review/approval commands and ODK export/build commands. |
| API | FastAPI app with `GET /health` and `GET /api/config`. | Document, candidate, review, export, ODK validation/build, and audit endpoints. |
| Persistence | SQLAlchemy models for literature documents, Zotero/literature sources, extraction runs, and candidate terms. Local SQLite default. | Review decision table, audit table, ODK export/build tables, Alembic migrations. |
| Extraction | Prompt generation, mock-output parsing, Pydantic validation, candidate persistence, duplicate skipping. | Real LLM provider execution and relation extraction persistence. |
| Review policy | Pydantic review statuses and approved-only export predicate. | Persistent review workflow and review UI/API. |
| ODK integration | Preview of the intended ROBOT template export path. | Writing TSVs, running ODK/Make, Git branch/commit/PR workflow. |
| Zotero | Offline JSON import, Web API metadata sync, source listing/showing, conservative document linking. | Attachment download/ingestion and write-back to Zotero. |
| Tests | Pytest coverage for ingestion, extraction, Zotero workflows, ODK preview path, and review export policy. | End-to-end review/export/ODK validation tests. |

Package metadata in `pyproject.toml` defines the project as `ontology-curation-assistant`, exposes the `oca` CLI entry point, and includes FastAPI, Typer, SQLAlchemy, Pydantic, Rich, pypdf, and httpx.

## 3. End-to-End Workflow

The intended workflow is:

```text
literature files
  -> ingestion
  -> text extraction
  -> candidate extraction
  -> candidate persistence
  -> human review
  -> approved candidates
  -> ODK/ROBOT TSV export
  -> ODK validation/build
  -> curator review / Git review
```

Current implementation status:

| Step | Status | Code path |
| --- | --- | --- |
| Literature files | Implemented | Files are read from a local directory by `oca ingest`. |
| Ingestion | Implemented | `backend/app/cli.py`, `LiteratureDocument.from_path()` in `backend/app/models/db.py`. |
| Text extraction | Implemented for text-like files and PDFs | `.txt`, `.md`, `.tsv`, `.csv` use `Path.read_text`; `.pdf` uses `pypdf.PdfReader`. |
| Candidate extraction prompt | Implemented | `backend/app/extraction/prompts.py`. |
| Real LLM call | Not implemented | `oca extract-candidates` refuses provider execution even if `OCA_LLM_PROVIDER` is set. |
| Mock LLM output | Implemented | `--mock-output` reads JSON from disk. |
| Candidate validation | Implemented | `backend/app/extraction/parser.py`. |
| Candidate persistence | Implemented | `backend/app/extraction/service.py`, `CandidateTermRecord`. |
| Human review | Mostly planned | Review statuses exist, but no CLI/API command changes candidate status. |
| Approved-only export policy | Implemented as pure function | `backend/app/review/policy.py`. |
| ODK TSV export | Not implemented | No code writes `ai_approved_terms.tsv`. |
| ODK validation/build | Not implemented | `build_command_candidates()` returns strings only; it does not execute commands. |
| Git branch/PR workflow | Not implemented | Mentioned in docs only. |

## 4. CLI Workflow

The CLI is implemented in `backend/app/cli.py` using Typer. It reads configuration through `backend/app/config.py`.

### Configuration and ODK

| Command | What it does | Reads/writes | ODK repository effect |
| --- | --- | --- | --- |
| `oca doctor` | Prints app name, database URL, ODK home, whether ODK home exists, and configured ontology repo. | Reads settings and filesystem existence. | None. |
| `oca odk-preview [--ontology-repo PATH]` | Prints the path where approved term TSV output would go. | Reads settings or CLI path. | None. No file is written. |

Examples:

```powershell
.\.venv\Scripts\Activate.ps1
oca doctor
oca odk-preview --ontology-repo C:\Users\ge47vob\ontology-development-kit\target\ppo
```

### Literature

| Command | What it does | Reads/writes | ODK repository effect |
| --- | --- | --- | --- |
| `oca ingest <literature_dir>` | Recursively registers files and extracts content for supported file types. | Reads local files; writes `literature_documents`. | None. |
| `oca literature-list` | Lists ingested documents. Shows linked Zotero source/citation when present. | Reads local database. | None. |
| `oca literature-show <document_id> [--chars N]` | Shows one document's metadata and extracted text prefix. | Reads local database. | None. |

Examples:

```powershell
oca ingest .\literature
oca literature-list
oca literature-show 1 --chars 2000
```

### Candidate Extraction and Candidate Display

| Command | What it does | Reads/writes | ODK repository effect |
| --- | --- | --- | --- |
| `oca extract-candidates <document_id> --prompt-out <path>` | Builds and writes the exact extraction prompt, then exits. | Reads `literature_documents`; writes prompt file. | None. |
| `oca extract-candidates <document_id> --mock-output <path>` | Parses mock JSON, validates it, stores candidates. | Reads JSON file and database; writes `extraction_runs` and `candidate_terms`. | None. |
| `oca extract-candidates <document_id> --mock-output <path> --dry-run` | Validates and prints candidates without storing them. | Reads JSON file and database. | None. |
| `oca extract-candidates <document_id>` | Fails unless a future provider implementation is added. | Reads settings/document. | None. |
| `oca candidates-list` | Lists persisted candidate terms. | Reads `candidate_terms`. | None. |
| `oca candidate-show <candidate_id_or_db_id>` | Shows full details for one candidate. | Reads `candidate_terms`. | None. |

Examples:

```powershell
oca extract-candidates 1 --prompt-out candidate_prompt.txt
oca extract-candidates 1 --mock-output .\mock_llm_output.json --dry-run
oca extract-candidates 1 --mock-output .\mock_llm_output.json
oca candidates-list
oca candidate-show 1
```

### Zotero

| Command | What it does | Reads/writes | ODK repository effect |
| --- | --- | --- | --- |
| `oca zotero-import <metadata_file>` | Imports offline Zotero/CSL/Better BibTeX-like JSON metadata. | Reads JSON file; writes `literature_sources`. | None. |
| `oca zotero-list` | Lists imported/synced Zotero source records. | Reads `literature_sources`. | None. |
| `oca zotero-show <source_id>` | Shows full metadata for one source. | Reads `literature_sources`. | None. |
| `oca zotero-link-documents <literature_dir> [--force]` | Conservatively links already ingested documents to sources. | Reads documents and sources; updates `literature_documents.source_id`. | None. |
| `oca zotero-config` | Prints Zotero sync configuration without printing the API key. | Reads settings. | None. |
| `oca zotero-sync [options]` | Syncs metadata from Zotero Web API. | Reads API, writes `literature_sources` unless `--dry-run`. | None. |

Examples:

```powershell
oca zotero-import .\zotero-export.json
oca zotero-list
oca zotero-show 1
oca zotero-link-documents .\literature

oca zotero-config
oca zotero-sync --library-type user --library-id 123456 --dry-run
oca zotero-sync --library-type group --library-id 123456 --collection COLLECTIONKEY --limit 25
```

## 5. ODK Connection

Configuration lives in `backend/app/config.py`:

| Setting | Environment variable | Default/current meaning |
| --- | --- | --- |
| `odk_home` | `OCA_ODK_HOME` | Defaults to `C:\Users\ge47vob\ontology-development-kit`. |
| `ontology_repo` | `OCA_ONTOLOGY_REPO` | Optional path to an ODK-managed ontology repository. For PPO, use `C:\Users\ge47vob\ontology-development-kit\target\ppo`. |
| `template_dir` | `OCA_TEMPLATE_DIR` | Defaults to `src/ontology/templates`. |
| `default_template_file` | `OCA_DEFAULT_TEMPLATE_FILE` | Defaults to `ai_approved_terms.tsv`. |

The expected PPO export target is:

```text
C:\Users\ge47vob\ontology-development-kit\target\ppo\src\ontology\templates\ai_approved_terms.tsv
```

Existing ontology inputs should be treated according to their role in the ODK project. Edit the maintained project ontology only for terms that belong in that ontology; place external ontology sources, extracted imports, mappings, or templates under the project's `src/ontology` tree and wire them through the project's ROBOT commands and Makefile targets. Common input locations are:

```text
src/ontology/imports/
src/ontology/templates/
src/ontology/mappings/
```

After a PPO ODK build, the generated simplified ontology should be inspected at a path similar to:

```text
target/ppo/src/ontology/ppo-simple.obo
```

This file is the built ontology output after imports, templates, ROBOT steps, and Make targets have been applied. Validate it with the project `make test` target and inspect it with ROBOT, Protégé, or OBO tooling before upload or GitHub submission.

`oca odk-preview` constructs this path by combining:

```text
OCA_ONTOLOGY_REPO / OCA_TEMPLATE_DIR / OCA_DEFAULT_TEMPLATE_FILE
```

or by using the `--ontology-repo` CLI option in place of `OCA_ONTOLOGY_REPO`.

Example:

```powershell
$env:OCA_ONTOLOGY_REPO="C:\Users\ge47vob\ontology-development-kit\target\ppo"
oca odk-preview
```

Current behavior is preview/path-oriented only. The command does not:

- create `ai_approved_terms.tsv`,
- inspect candidates,
- filter approved candidates,
- run ROBOT,
- run `make`,
- create a Git branch,
- commit files,
- open a pull request.

## 6. What the Code Currently Does with ODK

The actual ODK code is in `backend/app/odk/integration.py`.

Implemented objects/functions:

- `OdkProjectConfig`: dataclass with `repo_path`, `template_dir`, and `default_template_file`.
- `preview_export_path(config)`: returns `config.repo_path / config.template_dir / config.default_template_file`.
- `build_command_candidates()`: returns `["make test", "make prepare_release"]`.

`build_command_candidates()` only returns candidate command strings. Nothing in the code executes those commands.

The ODK code does not currently:

- write ROBOT template TSV files,
- generate SSSOM files,
- call ROBOT,
- call ODK,
- call `make`,
- parse validation errors,
- create Git branches,
- commit generated files,
- open pull requests.

The broader ODK workflow in `docs/odk-integration.md` is a target design, not implemented behavior.

## 7. Local Database and Persistence

The database layer is in `backend/app/db/session.py`.

Current default database URL:

```text
sqlite:///./oca.sqlite3
```

The project uses `Base.metadata.create_all(bind=engine)` plus a small `ensure_runtime_schema()` helper for SQLite column additions. Alembic migrations are not implemented.

Implemented SQLAlchemy tables/models in `backend/app/models/db.py`:

| Model | Table | Purpose |
| --- | --- | --- |
| `LiteratureDocument` | `literature_documents` | Ingested files and extracted text content. |
| `LiteratureSource` | `literature_sources` | Zotero/offline bibliographic metadata. |
| `ExtractionRun` | `extraction_runs` | Prompt/extraction metadata and raw response for mock extraction. |
| `CandidateTermRecord` | `candidate_terms` | Persisted candidate term suggestions awaiting review. |

`LiteratureDocument` stores path, filename, suffix, size, optional `source_id`, extracted `content`, and `created_at`.

`LiteratureSource` stores Zotero-style source metadata: provider, provider item key, citation key, title, normalized title, creators JSON, year, DOI, normalized DOI, URL, abstract, tags JSON, collections JSON, Zotero version, item type, sync timestamp, and timestamps.

`ExtractionRun` stores document id, provider, model, prompt name/version, raw response, and timestamp.

`CandidateTermRecord` stores deterministic candidate id, document id, optional extraction run id, label, normalized label, proposed definition, synonyms JSON, proposed parent, confidence score, review status, evidence JSON, and timestamp. It has duplicate protection by `(document_id, normalized_label)` and by `candidate_id`.

Review decisions are not stored in a dedicated table yet. Audit events are a Pydantic model in `backend/app/audit/events.py`, not a persisted table.

## 8. Candidate Extraction

Candidate extraction is implemented as a structured scaffold, not as a live LLM integration.

Implemented pieces:

- `backend/app/extraction/prompts.py` builds a curator-focused prompt.
- The prompt excludes author names, institutions, journal names, download headers, bibliographic artifacts, malformed PDF fragments, generic phrases, overly broad terms, and phrases unsuitable as ontology classes.
- The default prompt context window is `12000` characters.
- `--chars` can override the prompt context length.
- `--prompt-out` writes the exact prompt and exits.
- `--mock-output` reads a JSON response from disk.
- `backend/app/extraction/parser.py` validates the response with Pydantic.
- `backend/app/extraction/service.py` creates an `ExtractionRun` and persists `CandidateTermRecord` rows.
- Duplicate candidates for the same document/normalized label are skipped.

Expected mock response shape:

```json
{
  "candidates": [
    {
      "label": "preferential hydration",
      "proposed_definition": "Definition text.",
      "synonyms": ["water of preferential hydration"],
      "proposed_parent": "protein-solvent interaction",
      "confidence_score": 0.92,
      "evidence": [
        {
          "quoted_text": "Exact quote.",
          "section_title": null,
          "page_number": null,
          "char_start": null,
          "char_end": null,
          "direct_or_inferred": "direct"
        }
      ]
    }
  ]
}
```

Validation rejects malformed JSON, missing `candidates`, empty labels, empty evidence, confidence scores outside `0.0..1.0`, and invalid `direct_or_inferred` values.

Real LLM provider execution is not implemented. If `oca extract-candidates <document_id>` is run without `--prompt-out` or `--mock-output`, the CLI raises a clear error. If `OCA_LLM_PROVIDER` is configured, it still raises an error saying that provider implementation is not available yet.

There are JSON schemas in `schemas/`, and prompt templates in `prompts/extraction/`. The active CLI prompt builder is the Python implementation in `backend/app/extraction/prompts.py`; the Markdown prompt files are reference/versioned templates.

## 9. Human Review and Safety Boundary

Review statuses are defined in `backend/app/models/core.py` as `ReviewStatus`:

```text
new
in_review
needs_more_evidence
approved
approved_with_edits
rejected
deferred
exported_to_odk
odk_validation_failed
merged
```

The approved-only export rule is implemented in `backend/app/review/policy.py`:

```python
EXPORTABLE_STATUSES = {
    ReviewStatus.APPROVED,
    ReviewStatus.APPROVED_WITH_EDITS,
}
```

`can_export_to_odk(candidate)` returns true only for `approved` and `approved_with_edits`.

Important limitation: this rule is tested, but it is not yet connected to a TSV export implementation because ODK export does not exist yet. Current persisted candidate rows default to `review_status="new"`, and no CLI/API command currently approves or rejects them.

## 10. Zotero Workflow

Zotero support is metadata-only.

Implemented modules:

- `backend/app/zotero/importer.py`
- `backend/app/zotero/client.py`

Offline import:

- `oca zotero-import <metadata_file>` reads a JSON list.
- It supports CSL JSON-like items and Zotero Web-API-like item objects.
- Items without usable titles are skipped.
- Duplicate/update behavior uses provider item key, citation key, DOI, then normalized title.

Web API sync:

- `oca zotero-sync` uses `ZoteroApiClient`.
- Base URL defaults to `https://api.zotero.org`.
- Headers include `Zotero-API-Version: 3`.
- If an API key is configured, the client sends `Zotero-API-Key: <key>`.
- User library URL shape: `/users/<library_id>/items`.
- Group library URL shape: `/groups/<library_id>/items`.
- Collection URL shape: `/users/<library_id>/collections/<collection_key>/items` or `/groups/<library_id>/collections/<collection_key>/items`.
- Pagination follows `Link` headers with `rel="next"`.
- `--dry-run` fetches/parses but does not persist.
- `--limit` caps fetched/imported items.

Filtering:

- API items with `data.itemType` of `attachment`, `note`, or `annotation` are skipped.

Citation key behavior:

- Uses `data["citationKey"]` or top-level `citationKey` when present.
- Can parse `Citation Key: ...` from `data["extra"]`.
- Does not use `meta.creatorSummary` as a citation key.

Document linking:

- `oca zotero-link-documents <literature_dir>` links already ingested documents to sources.
- Matching is conservative:
  - citation key contained in filename,
  - source DOI found in document content,
  - normalized source title contained in filename or content.
- Ambiguous matches are skipped.
- Existing links are not overwritten unless `--force` is used.

Not implemented:

- PDF attachment download,
- attachment ingestion from Zotero,
- writing any changes back to Zotero.

## 11. API Workflow

The FastAPI app is in `backend/app/main.py`.

Implemented endpoints:

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Returns `{"status": "ok", "service": settings.app_name}`. |
| `GET /api/config` | Returns app name, ODK home path, whether ODK home exists, ontology repo path, and `require_human_approval`. |

The route module is `backend/app/api/routes.py`.

Planned endpoints listed in `docs/api.md` but not implemented in code:

```text
POST /api/corpora
POST /api/documents/upload
POST /api/extraction-runs
GET /api/candidates
GET /api/candidates/{candidate_id}
PATCH /api/candidates/{candidate_id}/review
GET /api/relations
PATCH /api/relations/{relation_id}/review
POST /api/exports/odk
POST /api/odk/validate
POST /api/odk/build
GET /api/audit
```

## 12. Tests

Run tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Current test coverage includes:

- CLI ingest missing directory and text-file ingestion.
- Literature show missing document behavior.
- Prompt generation.
- `extract-candidates --prompt-out`.
- Mock candidate extraction persistence.
- Dry-run extraction.
- Candidate validation failures.
- Duplicate candidate skipping.
- Candidate list/show behavior.
- ODK preview path construction.
- Review policy export eligibility.
- Offline Zotero import, duplicate update, list/show, linking, ambiguity, and force relinking.
- Zotero Web API URL/header construction, normalization, dry-run, persistence/update, CLI overrides, config errors, HTTP errors, invalid JSON, and pagination.

The tests do not call a real LLM provider or the real Zotero API.

## 13. What Is Not Implemented Yet

Based on the current code, these features are still missing or planned:

- Real LLM provider execution.
- Candidate review CLI/API.
- Review decision persistence.
- Review UI.
- Relation extraction persistence.
- Evidence segment table.
- Audit event persistence.
- ODK TSV generation.
- Approved-only ODK export command.
- ODK/ROBOT validation execution.
- ODK/Make build execution.
- Git branch creation, commits, and pull request workflow.
- Authentication and reviewer roles.
- Alembic migrations.
- Zotero attachment download/ingestion.
- Writing back to Zotero.
- Production deployment configuration.

## 14. Recommended Next Development Steps

The next milestone should be the minimal review/export bridge.

1. Add persistent review decisions.
   - Add a `review_decisions` table.
   - Store candidate id, reviewer, decision, old status, new status, comment, and timestamp.
   - Preserve status history rather than overwriting without trace.

2. Add candidate approval/rejection commands and API endpoints.
   - CLI examples: `oca candidate-approve <id>`, `oca candidate-reject <id>`, `oca candidate-mark-needs-evidence <id>`.
   - API endpoint: `PATCH /api/candidates/{candidate_id}/review`.
   - Keep status values aligned with `ReviewStatus`.

3. Implement approved-only ROBOT TSV export.
   - Add `oca odk-export-preview` and `oca odk-export`.
   - Export only `approved` and `approved_with_edits`.
   - Generate `src/ontology/templates/ai_approved_terms.tsv`.
   - Include candidate id, label, definition, parent, synonyms, evidence reference, and source document/source metadata where possible.

4. Add tests proving rejected/pending candidates are not exported.
   - Include `new`, `in_review`, `rejected`, and `deferred` negative cases.
   - Include `approved` and `approved_with_edits` positive cases.
   - Verify no unapproved rows appear in generated TSV.

5. Add optional ODK validation command.
   - Start with a dry-run or explicit command preview.
   - Then add a controlled command runner for configured ODK/Make targets.
   - Capture logs and map validation failures back to candidate/template rows when possible.

6. Add Git workflow only after export and validation are stable.
   - Branch creation.
   - Commit generated files.
   - Pull request creation.

## 15. Example Working Session

From the OCA repository root:

```powershell
# Activate environment
.\.venv\Scripts\Activate.ps1

# Install package and development dependencies
python -m pip install -e ".[dev]"

# Inspect configuration
oca doctor

# Point OCA at the PPO ODK repository for this shell
$env:OCA_ONTOLOGY_REPO="C:\Users\ge47vob\ontology-development-kit\target\ppo"

# Preview the intended ODK template export path
oca odk-preview
# Expected:
# C:\Users\ge47vob\ontology-development-kit\target\ppo\src\ontology\templates\ai_approved_terms.tsv

# Ingest local literature
oca ingest .\literature

# List documents
oca literature-list

# Inspect one document's extracted text
oca literature-show 1 --chars 2000

# Generate an extraction prompt without calling an LLM
oca extract-candidates 1 --prompt-out candidate_prompt.txt

# Optional: validate and preview mock extraction output without persisting
oca extract-candidates 1 --mock-output .\mock_llm_output.json --dry-run

# Optional: persist mock-extracted candidates
oca extract-candidates 1 --mock-output .\mock_llm_output.json

# Inspect persisted candidates
oca candidates-list
oca candidate-show 1
```

Zotero metadata example:

```powershell
# Offline import
oca zotero-import .\zotero-export.json
oca zotero-list
oca zotero-link-documents .\literature

# Web API metadata sync configuration, without printing the API key
oca zotero-config

# Web API dry run
oca zotero-sync --library-type user --library-id 123456 --dry-run
```

This session does not modify the ODK repository. At the current implementation level, `oca odk-preview` only prints the path where a future approved-only TSV export should be written.
