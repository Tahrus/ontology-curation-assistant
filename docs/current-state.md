# Current Project State

Last reviewed: 2026-06-25

## Summary

Ontology Curation Assistant is currently an early working scaffold for a human-in-the-loop ontology curation workflow. The repository already has a FastAPI backend, a Typer command-line interface, SQLAlchemy-backed local persistence, ODK integration helpers, review policy logic, JSON schemas, prompt templates, and tests for the implemented slices.

The main implemented value today is a local browser workflow for configuration, project creation/selection, Zotero metadata sync, local PPO ontology readout, candidate extraction/curation, structured project suggestion review, evaluation metrics, OLS/local ontology matching, tree-based ontology visualization, rejection management, and approved-candidate export, plus CLI support for the underlying ingestion, Zotero, LLM test, project, curation-run, evaluation, and project ODK workflows. A standalone `zotero_lit_md` CLI package now exports Zotero Desktop local PDF attachments into full-text LLM/RAG-ready Markdown.

The canonical literature repository is active-project scoped and two-stage. Existing `sources/`, `markdown/`, and `metadata/` outputs are preserved as pipeline-generated staging; human-approved entries live under `curated/{markdown,metadata}`. Candidate extraction, curation suggestions, and `combined_literature.md` use curated entries only. Zotero sync compares Zotero metadata against staged and curated local entries before import, using DOI, PII, PMID/PMCID, arXiv ID, ISBN, ISSN+title, URL, then normalized title+year so new entries are imported without duplicating existing literature. `publisher_api_required` is the default extraction mode: Zotero supplies identifiers/metadata and structured full-text providers are tried before Markdown is generated. The working Elsevier XML path is preserved as the first provider adapter and still uses the existing Article Retrieval XML parser/converter. Elsevier attempts only its real PII/DOI endpoints and records unsupported identifiers. When structured full text is unavailable, the importer creates a blocked metadata-only staged entry with a source report and `manual_markdown_required` instead of silently starting PDF extraction. ACS DOI imports use Crossref metadata/link inspection, record PDF links as `pdf_available_but_not_used`, and request manual structured Markdown unless an explicit PDF fallback mode is selected. Manual Markdown can be uploaded and validated; only validated Markdown becomes canonical staged Markdown that can be promoted. Books, book chapters, conference papers, and reports are stored in the same repository with a `literature_type`, retained ISBN/book metadata, the same project-tag behavior, and the same staged/curated flow. Projects expose exactly one canonical project tag (`ontology_id`), while old slug/id/name tag aliases are normalized and preserved as legacy metadata when encountered. `pdf_fallback_allowed` and `pdf_only` keep PyMuPDF available only through explicit user/config authorization, recorded in provenance. XML conversion retains nested sections, captions, tables, appendices/back matter, and references. New metadata records carry a repository-relative artifact manifest plus provider attempts, identifier-used/attempt provenance, fulltext/Markdown/source-quality statuses, metadata/Markdown quality reports, extraction mode, API diagnostics, XML/PDF use, fallback use/authorization, and content/metadata source fields. Isolated API tests write optional `api_tests/` XML/Markdown without staging or reading PDFs. Confirmed cleanup previews first, removes unpromoted and orphan artifacts only from known OCA-managed folders in both the active project repository and a distinct configured legacy global repository, protects curated/promoted/external files, and repairs combined output from curated entries. Existing canonical entries are non-destructively treated as staged/needs-review because prior manual curation cannot be inferred safely. Settings loads missing publisher values with safe defaults, stores masked secrets with environment precedence, permits clearing stored credentials, exposes the extraction mode, and lists the masked Elsevier configuration alongside saved Zotero/LLM configurations.

## Implemented Capabilities

### Backend API

The FastAPI application is defined in `backend/app/main.py`.

Implemented endpoints:

- `GET /health`: returns service health and app name.
- `GET /api/config`: returns selected runtime configuration, including ODK path status, ontology repository path, and human-approval setting.
- Browser pages: `/`, `/config`, `/zotero`, `/literature`, `/ontology`, `/curation-prompt`, `/curation`, `/export`.
- Project browser pages: `/projects`, `/suggestions`, and `/evaluation` for project creation/selection, structured project suggestions, expert review decisions, and evaluation metrics.
- Browser UI includes client-side route handling for dashboard/header links, a persistent active-project banner, project hierarchy dashboard, page-scoped startup data loading, a visible startup/page error path, accessible button/link click feedback, long-running action busy states, a Light/Dark theme toggle persisted in local storage, and a smaller shared logo link back to the dashboard.
- Browser Configuration includes guarded Zotero metadata-sync controls, provider/model dropdowns for Gemini, OpenAI, Anthropic, and custom OpenAI-compatible LLMs, preset defaults for model/base URL/env var/runtime settings, API key environment variable support, a `Test LLM connection` action with key-source and canonical provider-key diagnostics, publisher/source API settings for Elsevier, Springer, Wiley, Crossref, NCBI, and OpenAlex with masked status diagnostics, and Docker/ODK diagnostics for mounted paths and tools. The Literature page separates `Curated Literature` from `New / Uncurated Literature` in sub-tabs; both views support search/status filtering, project-tag filtering, provenance/status display, and review/edit actions.
- Configuration: `/api/config/status`, `/api/config/zotero`, `/api/config/llm`, `/api/config/ontology-path`, `/api/config/test-zotero`.
- Two-stage literature APIs cover staged/curated listing, staged review/edit/promote/reject, curated edit/project tags, publisher-API-required identified import, explicitly authorized PDF modes, import diagnostics, isolated publisher API testing, dry-run/confirmed unpromoted cleanup with legacy managed-orphan repair, and publisher settings. Import remains `/api/literature/import`; diagnostics are `/api/literature/import-diagnostics` and `/api/literature/test-publisher-api`; `/api/literature/pipeline/run` remains a compatibility alias that obeys the configured mode.
- Saved Zotero, LLM, and publisher API configurations: `/api/config/saved`, `/api/config/saved/{id}/activate`, and deletion. Elsevier API keys and institutional tokens are masked.
- Zotero: `/api/zotero/test`, `/api/zotero/sync`, `/api/zotero/entries`, `/api/zotero/entries/{id}`, `/api/zotero/import-test`.
- Existing ontology: `/api/ontology/status`, `/api/ontology/scan`, `/api/ontology/select-file`, `/api/ontology/index`, `/api/ontology/terms`, `/api/ontology/terms/{term_id}`, `/api/ontology/search`, `/api/ontology/graph`. The browser Ontology page now treats `/api/ontology/status` as active-project scoped by default and shows a no-project warning instead of using stale global ontology data.
- Existing ontology also exposes `/api/ontology/tree`, which builds tree-ready data with nodes, synonyms/source metadata, `edgeType: "hierarchy"` subclass edges, `edgeType: "semantic"` lateral relation edges, root IDs, source metadata, and warnings. It is now the default browser ontology visualization.
- Existing ontology exposes `/api/ontology/relation-types`, a backend-owned relation catalogue used by graph-assisted candidate review. Entries include labels, ontology IDs where available, inverse labels, short descriptions, and simple source/target expectations.
- Existing ontology term and search endpoints return controlled client errors when the selected ontology file cannot be parsed, rather than leaking a raw server error into browser startup.
- Meta-ontology graph: `/api/meta-ontology/graph` remains available as a compatibility endpoint, but it is no longer the dashboard widget.
- Projects: `/api/projects`, `/api/projects/active`, `/api/projects/{project_ref}`, `/api/projects/{project_ref}/select`, `/api/projects/{project_ref}/activate`, `/api/projects/{project_ref}/children`, `/api/projects/{project_ref}/odk/validate`, `/api/projects/{project_ref}/odk/logs`, and `/api/projects/{project_ref}/exports/accepted.robot.tsv`.
- Curation prompt and suggestions: `/api/curation/prompt` for load/save/reset of the editable prompt and `/api/curation/suggestions/run` for the LLM curation request using the saved prompt, selected `.obo` ontology, and current `combined_literature.md`.
- LLM provider metadata and diagnostics: `/api/config/llm/providers`, `/api/config/llm/test`, and `/api/diagnostics/docker-odk`.
- Project curation runs and structured suggestions: `/api/curation/prompt-strategies`, `/api/curation/runs`, `/api/curation/runs/{run_id}/suggestions`, `/api/suggestions`, and `/api/suggestions/{suggestion_id}/review`.
- Evaluation: `/api/evaluation/compute` and `/api/evaluation/compare`.
- Literature and candidates: `/api/literature`, `/api/literature/repository/review`, `/api/literature/doctor`, `/api/literature/repository/report`, `/api/literature/context/build`, literature regenerate/retry actions, `/api/extraction/candidates`, `/api/candidates`, `/api/candidates/{id}`, review, OLS matching, local ontology matching, match selection, graph-review proposal persistence, and decision endpoints. The default active candidate queue includes draft/in-review/deferred/needs-more-evidence records and excludes approved or rejected records.
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
- Literature-changing CLI workflows refresh the LLM-ready Markdown repository under `literature/papers` by default. Each paper is stored as a deterministic `.md` file with YAML front matter for stable metadata, metadata-match status, document role, automatic-extraction flags, and Markdown sections for abstract, notes, and ontology-relevant extracted content.
- Candidate extraction loads Markdown repository files, requires usable `ready_for_llm` records for automatic domain extraction, excludes metadata mismatches, incomplete/blocked/needs-review/failed files, manual-review records, methodology articles, and supplementary files, and combines the remaining structured LLM context plus cleaned evidence into one Markdown corpus. The former literature JSON sidecar has been removed and is no longer generated or read.
- `oca literature reset-repository --yes` and `POST /api/literature/repository/reset` reset the configured literature base directory recursively, recreate the empty directory, clear stored literature rows/extraction state, log deleted items, refuse unsafe root-like targets, unlink symlinks instead of following them, and leave ontology outputs, settings, GitHub configuration, and ODK files untouched when those outputs are outside the literature base.
- `oca literature import/list/reset/deduplicate/build-combined/migrate-old --project <slug>` operate on `projects/<slug>/literature`. DOI/PII/title identity prevents duplicate entries; apply operations back up data, migration archives legacy files, and re-import preserves curation fields. `oca literature pipeline` routes to the canonical implementation for compatibility.
- `oca literature doctor/validate/report/retry-extraction/regenerate-clean/regenerate-context/build-combined-context` expose extractor availability, repository validation/reporting, per-paper artifact refresh, retry metadata, and role-specific combined context generation.
- `oca llm-ontology-suggestions` creates a traceable ontology-suggestion prompt/export from the canonical Markdown literature repository. `--dry-run` needs no credentials and writes a schema-valid empty suggestion payload; non-dry-run mode requires configured provider-neutral LLM credentials and validates the required `suggestions` JSON shape.
- `oca llm-test` tests the configured LLM provider with a tiny prompt and reports provider, canonical provider key, model, key presence/source, latency, and concise diagnostics.
- `oca project create/list/select/show`: creates/selects project records and the local project folder layout.
- `oca curation run/list-runs/review-summary/review`: creates project curation runs, optionally parses structured suggestion JSON, lists runs, summarizes reviews, and stores expert review decisions.
- `oca evaluation compute/compare/export`: calculates reproducible metrics from stored suggestions/reviews and compares runs by label/triple overlap.
- `oca ontology init-odk/validate/export-templates/build/test`: initializes project ODK folders, validates/logs ODK metadata, exports accepted/edited suggestions, and records build/test requests as pending manual operations until safe execution is configured.
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

- `projects`
- `literature_documents`
- `literature_sources`
- `extraction_runs`
- `candidate_terms`
- `app_settings`
- `curation_runs`
- `suggestions`
- `review_decisions`
- `evaluation_metrics`
- `odk_operation_logs`

Stored document fields now include optional project-scoping and literature-processing metadata:

- `id`
- `project_id`
- `path`
- `filename`
- `suffix`
- `size_bytes`
- `content`
- `title`, `authors_json`, `year`, `doi`
- `source_pdf_path`, `markdown_path`, `extraction_status`, `content_hash`, `duplicate_group_id`
- `created_at`

The larger intended schema is described in `docs/database-schema.md`. Literature sources, extraction runs, candidate terms, curation runs, structured suggestions, review decisions, evaluation metrics, and ODK operation logs now have persistence tables. Existing literature/source/candidate rows remain valid because project IDs are nullable during the compatibility transition. Richer evidence segmentation, audit events, and formal migrations are still planned.

### Project-Based Curation

- Project records with slug, ontology metadata, project type, optional parent project, short description, minimal scope notes, namespace/prefix, local path, optional ODK/editable/built/literature/local-Git paths, GitHub URL, timestamps, and active-project flag.
- Project folder creation under `projects/<project_slug>/` with separate `literature`, `ontology`, `curation`, `evaluation`, and `logs` areas plus `project.json`.
- Active project selection through API, UI, and CLI.
- Browser project-management scaffolding for creating/editing/selecting projects through a four-step wizard, project cards, a selected-project detail/next-step panel, parent/child project hierarchy, existing ontologies as normal `existing_ontology_project` nodes, base IRI suggestions until manual override, optional configured-LLM metadata drafts, preserved field values on failed saves, structured project errors, and optional path statuses as warnings rather than hard failures.
- Dashboard display of active project metadata and project hierarchy: project name, project type, ontology ID/prefix, parent, children, workspace/repository metadata, optional ODK/editable ontology/built ontology/literature path statuses, tagged-literature count, nested project tiles, active-project highlighting, and tile activation.
- Backend validation for required project name and ontology ID, unique ontology ID, supported project type, self-parent rejection, circular-parent rejection, and basic base IRI shape.
- Zotero-backed literature records can store explicit `project_tags_json` values independent of Zotero source tags. The Literature page can assign/remove project tags, and project payloads count entries tagged to the active project.
- Prompt strategy registry for `literature_only`, `ontology_only`, `literature_plus_ontology`, and `structured_relation_extraction`.
- Project curation-run records with model, prompt strategy, prompt text, context configuration, literature/ontology snapshot paths, raw output, status, and timestamp.
- JSON suggestion parser for the requested `suggestions` shape, including relations, synonyms, evidence, duplicate checks, confidence, raw LLM output, and malformed-output warnings.
- Persistent review decisions with statuses `accepted`, `edited`, `rejected`, `duplicate`, `unsupported`, and `further_review`, plus comments, optional edited fields, relation correctness, and review effort seconds.
- Evaluation metrics for accepted/edited precision, unsupported rate, duplicate rate, relation correctness, evidence traceability, total/average review effort, and review counts.
- Run comparison by exact label overlap, normalized label overlap, and relation triple overlap.
- Project TSV export that includes accepted and edited suggestions by default and excludes rejected, duplicate, unsupported, and further_review suggestions unless further_review is explicitly included.
- Project ODK validation/logging endpoints and CLI commands for safe metadata checks and operation logs.

### Zotero Literature Sources

The current Zotero integration supports both offline imports and metadata-only Web API sync.

Implemented:

- Import from CSL JSON-like Zotero/Better BibTeX exports.
- Import from a Zotero Web-API-like JSON item shape when present in exported files.
- Metadata-only sync from Zotero user or group libraries through the Zotero Web API.
- Zotero Desktop local API metadata sync when configured with library type `user`, library ID `0`, base URL `http://127.0.0.1:23119/api`, and an empty API key. The connection test fetches one item with the `Zotero-API-Version: 3` header and does not require a Zotero API key.
- Explicit local extraction from deposited Zotero PDF attachments remains available in `pdf_fallback_allowed` or `pdf_only` mode. It is not triggered by metadata sync in the default publisher-required mode.
- Browser sync defaults to no limit and follows Zotero pagination until all configured records are fetched.
- Browser literature records are shown by title with author/year/type/DOI/key metadata, an `Open in Zotero` URI only when a Zotero item key is valid and unambiguous, and an expandable JSON section for the corresponding record payload.
- The browser literature view merges Zotero database rows with matching Markdown repository entries when available and also displays repository-only Markdown records created by the integrated PDF import pipeline. The detail panel shows raw, clean, and LLM-context Markdown plus readable metadata rather than raw JSON. Candidate extraction from a Zotero source prefers the Markdown record over legacy metadata snippets.
- Literature review controls can filter by document role, document state, extraction quality, metadata mismatch, and manual-review status. Curators can update include/exclude, metadata-match status, role, manual-review flags, and state through `PATCH /api/literature/repository/review`, regenerate clean/context artifacts, record retry engines, block/unblock records, and build domain/review/methodology/excluded combined contexts.
- Browser Zotero sync stores identifiers and metadata, then attempts strict publisher XML imports for identified sources when an active project is selected. It returns visible per-item failures and never automatically scans Zotero storage or triggers PDF extraction in the default mode.
- Optional collection sync through configured or CLI-provided collection keys.
- Browser Zotero save/test/sync event handlers use stable element IDs, bind after the DOM is ready, report missing required panel elements clearly, and guard optional controls before calling nested selectors.
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

- `OCA_ODK_HOME`: `/odk` for Docker-oriented configuration, or a user-provided local ODK path
- Template directory: `src/ontology/templates`
- Default approved-term template: `ai_approved_terms.tsv`
- Default workflow template relative path: `templates/ai_approved_terms.tsv`
- Default validation command: `make test`
- Default workflow mode: dry-run

### Docker and ODK Runtime

Implemented:

- Root `Dockerfile` installs the Python app, static UI, Python dependencies, Java, `make`, `git`, and a ROBOT jar wrapper.
- `docker-compose.yml` starts the API on port 8000 and mounts persistent runtime state at `/data`, literature at `/data/literature`, local ontology files at `/ontology`, and the ODK workspace at `/odk`.
- `.env.example` uses configurable, non-machine-specific defaults and supports Gemini through `OCA_LLM_API_KEY_ENV_VAR=GEMINI_API_KEY`.
- `/api/diagnostics/docker-odk` and the Configuration page report ROBOT/Java/make/git availability plus ODK, ontology, and literature path existence.

Known limitation:

- Docker Compose config validates locally, but image build/start still depends on Docker Desktop or another Docker daemon being running.

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
- Ontology tree payloads for focused top-down parent-child browsing, root/search jumping, focus mode, depth limiting, expand/collapse, node selection details, lateral relation side links, relation labels, parse metadata/warnings, and larger-ontology-friendly rendering.
- The active browser Ontology page resolves ontology files from the active project, preferring an existing built/released ontology file and then an existing editable ontology file. Missing project paths are warnings; no active project returns a clear no-project status.

Local and OLS matches are never auto-selected. Curators must explicitly choose a match or mark a candidate as a new term proposal.

The ontology tree is now the default ontology visualization. The browser stores the full tree payload internally, derives a smaller visible section from the selected root/focus node, expansion state, and depth control, then lays out visible nodes from hierarchy edges only. Parent classes stay above subclasses and siblings are arranged horizontally. Clicking a node highlights it, dims unrelated visible nodes, updates a structured details panel, and displays source path, class count, and selected label/ID verification markers. Non-hierarchical ontology relations are overlaid as dashed semantic side links only for visible or focused nodes after positions are computed. The older circular graph endpoint remains available for compatibility but is not the default UI.

Candidate Curation includes a graph-assisted ontology context panel. Selecting a candidate and graph node can update proposed parent, relation source, relation target, duplicate target, and comparison notes. Proposed relations are stored in `graph_review_json` on the candidate and previewed as dashed graph edges; existing ontology files are not mutated by these graph actions.

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
- Optional provider-neutral LLM calls when Gemini, OpenAI, Anthropic, or custom OpenAI-compatible provider/API key settings are configured. Provider presets and UI/CLI alias normalization live in `backend/app/llm/presets.py`; labels such as `Gemini API`, `Google Gemini`, `google_gemini`, `google-ai`, and `google_ai` resolve to the canonical `gemini` provider before config save, saved-config activation, connection tests, and real LLM requests.
- The editable ontology curation prompt page assembles LLM requests in deterministic order: saved prompt, selected current ontology OBO content, `combined_literature.md`, and a JSON-only output requirement. Missing/empty literature, missing LLM credentials, or missing/non-OBO selected ontology files fail before the LLM call. Oversized literature is chunked explicitly using `OCA_LLM_CONTEXT_CHAR_LIMIT`; request traces and valid/invalid responses are written under `literature/curation_runs/` without API keys.
- Browser extraction no longer requires selecting an individual literature document or paper. When no source is passed, it loads all valid LLM-ready Markdown files from the configured literature repository, skips malformed files with warnings, combines valid entries into one Markdown corpus, and returns a controlled import-literature-first message when no valid files are available.
- Browser/API extraction supports `dry_run: true` to report included and excluded repository documents without persisting candidates.

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
- `OCA_LLM_API_KEY_ENV_VAR`
- `OCA_LLM_MODEL`
- `OCA_LLM_BASE_URL`
- `OCA_LLM_TEMPERATURE`
- `OCA_LLM_MAX_OUTPUT_TOKENS`
- `OCA_LLM_TIMEOUT_SECONDS`
- `OCA_LLM_RETRY_COUNT`
- `OCA_LLM_STREAM`
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

Verified on 2026-06-18 for the Zotero Metadata Sync frontend guard/local API fix:

- `node --check backend\app\static\app.js`
- `.\.venv\Scripts\ruff.exe check backend\app\api\routes.py backend\tests\test_browser_api.py backend\tests\test_zotero_api_sync.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_api.py backend\tests\test_zotero_api_sync.py` passed with 57 tests.

Verified on 2026-06-18 for the canonical literature state/quality/context workflow update:

- `node --check backend\app\static\app.js`
- `.\.venv\Scripts\ruff.exe check backend\app\literature\quality.py backend\app\literature\repository.py backend\app\api\routes.py backend\app\cli.py backend\tests\test_entry_generation.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_entry_generation.py backend\tests\test_browser_api.py` passed with 78 tests.

Verified on 2026-06-17 for the project-management scaffold task:

- `node --check backend\app\static\app.js`
- `.\.venv\Scripts\ruff.exe check backend\app\models\db.py backend\app\db\session.py backend\app\projects.py backend\app\api\routes.py backend\tests\test_project_workflow.py`
- `.\.venv\Scripts\python.exe -m py_compile backend\app\models\db.py backend\app\db\session.py backend\app\projects.py backend\app\api\routes.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_project_workflow.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_project_workflow.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest` passed with 178 tests.

Verified on 2026-06-17 for the Meta-UI/project-wizard/literature-tags update:

- `node --check backend\app\static\app.js`
- `.\.venv\Scripts\python.exe -m py_compile backend\app\models\db.py backend\app\db\session.py backend\app\projects.py backend\app\api\routes.py`
- `.\.venv\Scripts\ruff.exe check backend\app\models\db.py backend\app\db\session.py backend\app\projects.py backend\app\api\routes.py backend\tests\test_project_workflow.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_project_workflow.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest` passed with 180 tests.

Verified on 2026-06-17 for the project UI AI suggestion/form preservation/active-project ontology status fix:

- `node --check backend\app\static\app.js`
- `.\.venv\Scripts\python.exe -m py_compile backend\app\api\routes.py`
- `.\.venv\Scripts\ruff.exe check backend\app\api\routes.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest` passed with 183 tests.

Verified on 2026-06-17 for the project usability, detail view, active-project banner, and clearer project error messages update:

- `node --check backend\app\static\app.js`
- `.\.venv\Scripts\python.exe -m py_compile backend\app\api\routes.py`
- `.\.venv\Scripts\ruff.exe check backend\app\api\routes.py backend\tests\test_project_workflow.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_project_workflow.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest` passed with 183 tests.

Verified on 2026-06-17 for the dashboard project hierarchy replacement:

- `node --check backend\app\static\app.js`
- `.\.venv\Scripts\ruff.exe check backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_api.py backend\tests\test_project_workflow.py`
- `.\.venv\Scripts\python.exe -m pytest` passed with 183 tests.

Verified on 2026-06-17 for the active LLM code-path and Gemini provider-normalization task:

- `.\.venv\Scripts\ruff.exe check backend\app\llm\presets.py backend\app\llm\clients.py backend\app\api\routes.py backend\app\cli.py backend\tests\test_llm_clients.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_llm_clients.py backend\tests\test_browser_api.py`
- `.\.venv\Scripts\python.exe -m pytest`
- Direct backend check with `POST /api/config/llm` using provider `Gemini API` followed by `POST /api/config/llm/test` returned `provider_key: gemini`.

Verified on 2026-06-16 for this Docker/LLM/tree task:

- `node --check backend\app\static\app.js` passed.
- `.venv\Scripts\python.exe -m py_compile ...` passed for changed Python modules.
- `.venv\Scripts\python.exe -m pytest backend\tests\test_llm_clients.py backend\tests\test_curation_prompt.py backend\tests\test_browser_api.py` passed with 50 tests.
- `.venv\Scripts\ruff.exe check ...` passed for changed Python modules and tests.
- `docker compose config` passed.
- `docker compose build` could not complete because Docker Desktop's Linux engine was not running on the host.

Previously verified on 2026-06-02:

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
- Literature metadata title/DOI validation, metadata-mismatch exclusion, incomplete extraction gating, role classification, canonical document states, raw/clean/context/report/blocked artifact writing, manual-review/state metadata updates, extractor doctor/report endpoints, combined context building, extraction dry-run context-size reporting, and short-document LLM context construction
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
- Full migration framework; current upgrades remain SQLite-compatible runtime additions.
- Complete project-scoped replacement of every legacy literature/candidate path. Existing workflows still run against their established global paths unless invoked through the new project APIs/CLI.
- Ontology imports/dependencies and external reference relationships are intentionally not modeled in project metadata. They are deferred to later curation and ontology review work.
- Project metadata scaffolds do not create ontology terms, ontology files, ODK repositories, or GitHub repositories.
- Downloading missing Zotero attachments
- Writing changes back to Zotero
- Structured publisher retrieval currently supports automatic Elsevier Article Retrieval XML only. Provider scaffolds exist for arXiv, Crossref, ACS, PMC, PubMed, Springer/Wiley settings, Unpaywall, generic HTML, and PDF, but most are metadata/status adapters until real structured full-text integrations are implemented. Unsupported providers create metadata-only/manual-Markdown-required entries rather than silently parsing PDFs.
- Full production-grade AI/LLM extraction execution and retries beyond the current provider abstraction and basic retry setting
- OCR for scanned/image-only PDFs
- Reliable two-column reading-order reconstruction; current PyMuPDF extraction is best-effort and diagnostics can warn about quality issues
- Actual multi-engine PDF extraction fallback execution is still limited; the current doctor/retry workflow detects/records engine availability and retry intent, while explicitly authorized PDF modes remain PyMuPDF-first.
- BFO validation; later support should target BFO 2020 terminology and identifiers
- Static version-controlled relation catalogue for later prompt/validation constraints
- Audit log persistence
- Direct branch management and pull request workflow
- Production GitHub export UI for generated ontology artifacts and project-scoped push actions
- Verified Docker image build/start in this environment; `docker compose build` currently fails if Docker Desktop's Linux engine is not running.
- Authentication and reviewer roles
- Alembic migrations
- Production deployment configuration

## Current Safety Posture

The core safety boundary is already represented in code and tests:

- AI-generated or automatically extracted candidates are not treated as ontology changes.
- Only `approved` and `approved_with_edits` candidates are exportable.
- Current ODK functionality is preview-only, so the assistant does not mutate an ontology repository.

## Phase 2 Literature Quality Status

Implemented in this task:

- Default compatible artefact folders remain `literature/Paper-PDF`, `literature/Markdown`, `literature/papers`, and `literature/combined_literature.md`.
- Raw extracted Markdown is preserved separately from cleaned canonical per-paper Markdown and structured LLM-context Markdown.
- Per-paper Markdown front matter now includes canonical provenance and review fields where available, including `paper_id`, `zotero_key`, `zotero_item_key`, `pdf_path`, `pdf_sha256`, `source_filename`, `source_pdf`, `raw_markdown`, `extraction_method`, `extraction_date`, extraction engine metadata, `cleanup_version`, `state`, extraction metrics, `extraction_quality`, `metadata_match_status`, `doi_match_status`, `document_role`, `requires_manual_review`, warnings, and automatic-extraction include/exclude flags, while retaining compatibility fields.
- Cleanup rules are explicit, named, test-covered, and conservative; DOI-containing scientific text is retained.
- Cleanup and extraction diagnostics are written under `literature/metadata` and per-paper `reports`, and surfaced by the pipeline API/CLI as report paths and skipped-paper counts.
- Combined literature is generated from usable canonical per-paper Markdown, includes paper boundary comments, de-duplicates by paper ID, excludes references by default for LLM context, includes cleaned evidence text, and skips papers marked `failed`, `incomplete`, `blocked`, `requires_manual_review`, `metadata_mismatch`, or unsuitable document roles. Role-specific context bundles are written under `literature/combined`.
- Literature reset continues to clear the configured literature base directory, including generated metadata/diagnostic files.

Baseline before these fixes on 2026-06-10: `.\.venv\Scripts\python.exe -m pytest` reported 138 passed and 2 failed, both due to the pre-existing path-default mismatch; `.\.venv\Scripts\ruff.exe check` reported four pre-existing lint errors in the draft Phase 2 files.

## Recommended Next Steps

1. Add Alembic and formal migrations for the existing `literature_documents` table.
2. Add richer evidence segment storage and review decision tables.
3. Add persisted ontology index tables if indexing large ontologies becomes slow.
4. Add optional tooling to detect missing local Zotero attachments and report how to repair them outside the extraction path.
5. Implement real structured XML/HTML retrieval inside the new non-Elsevier provider adapters without weakening the strict no-silent-PDF boundary.
6. Harden the LLM providers with retries, model validation, and structured-output support.
7. Implement Phase 3 LLM curation workflow changes in the existing `backend/app/llm/curation.py`, `backend/app/llm/service.py`, `backend/app/api/routes.py`, prompt files, and schemas: bootstrap/curation modes, modular prompt profiles, final prompt preview/editing, strict JSON candidate schema, one malformed-JSON repair attempt, source-quote verification against canonical Markdown, component-specific confidence, operation types, temporary candidate UUIDs, and no LLM-generated permanent ontology IDs.
8. Add direct ODK repository write/validation actions for approved candidates only.
9. Add validation around exported rows and map validation errors back to candidate IDs.
10. Continue project scoping through the legacy literature pipeline and candidate extraction paths so all browser operations can optionally read/write inside the active project folder.
11. Add safe configured execution for project ODK build/test/import commands with clean-git/backup checks before writing templates or running external tools.
