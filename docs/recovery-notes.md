# Recovery Notes - Diagnostics and Stabilization

This document outlines the findings from Phase 0 (Stabilization and Diagnosis) to establish a baseline for recovering and enhancing the Ontology Curation Assistant.

## Project Structure

The project follows a standard layout separating the Python FastAPI backend, static frontend assets, literature storage, database, prompt/schema definitions, and ODK workspaces:

- `backend/app/`: FastAPI application code
  - `api/`: API route implementations (`routes.py`)
  - `audit/`: Audit logging schemas and event models
  - `db/`: Database connection and upgrade scripts (`session.py`)
  - `extraction/`: Prompt generation and parsing logic for LLMs
  - `literature/`: literature pipeline and Markdown loader/cleaner/exporter
  - `llm/`: LLM client abstraction layer and presets for provider normalization
  - `models/`: Pydantic and SQLAlchemy database models (`db.py`)
  - `odk/`: ODK templates, ROBOT integration, and workflow steps
  - `ontology/`: Local ontology loading, OBO parsing, tree generation, and relation lists
  - `review/`: Review policies defining candidate status changes
  - `services/`: Configuration parsing and runtime configuration management
  - `static/`: Static UI folder (HTML, CSS, JS) served by FastAPI
- `backend/tests/`: Diagnostic unit and integration test suite
- `docs/`: Developer guides and architecture documentation
- `literature/`: Local directory for literature processing artifacts
- `prompts/`: Curation prompts and templates
- `schemas/`: Structured JSON schemas for LLM validation
- `zotero_lit_md/`: Standalone CLI tool to extract PDFs from local Zotero storage to Markdown

## Key Component Mapping

- **API Routes**: Implementations are defined in [routes.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/api/routes.py).
- **UI Frontend**: Static assets are rendered in:
  - [index.html](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/static/index.html) (Markup & Controls)
  - [app.js](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/static/app.js) (Routing, SVG graph rendering, state management)
  - [styles.css](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/static/styles.css) (Styles & Theme tokens)
- **LLM Configuration & Connection Test**:
  - LLM providers are configured in [presets.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/llm/presets.py) and [clients.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/llm/clients.py).
  - LLM connection test endpoint `/api/config/llm/test` calls `test_llm_connection` in [clients.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/llm/clients.py#L69-L119).
- **Graph Data Loading**:
  - Main hierarchy & semantic relations: endpoint `/api/ontology/tree` in [routes.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/api/routes.py) loads files via [local.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/ontology/local.py).
  - Meta-ontology graph: `/api/meta-ontology/graph` in [routes.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/api/routes.py).
- **Graph Rendering**:
  - Rendered in [app.js](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/static/app.js) via `deriveVisibleOntologyTree()`, `layoutOntologyTree()`, and `renderOntologyTreeSvg()`.
- **Candidate Review**:
  - Implemented backend decision endpoints in [routes.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/api/routes.py) and status policies in [policy.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/review/policy.py).
  - Managed frontend-side in the Suggestions and Candidate Curation sections of [app.js](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/static/app.js).
- **ODK/ROBOT Export**:
  - Export TSV writing and downstream checks are located in [integration.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/odk/integration.py) and [workflow.py](file:///c:/Users/ge47vob/.antigravity/ontology-curation-assistant/backend/app/odk/workflow.py).

## Current Test Status

- **Running check**: pytest execution completed.
- **Failures**: 0 failures (171 passed out of 171 tests).
- All unit and integration tests are passing successfully.
