# Developer Guide

This guide is for Codex, Antigravity, and human maintainers working on the Ontology Curation Assistant.

## First Reads

Before changing code, read:

- `README.md`
- `docs/current-state.md`
- `docs/code-overview.md`
- the source files for the behavior being changed

Do not use Git history as the source of truth for current behavior. Inspect files directly and run focused tests.

## Common Commands

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest backend\tests\test_llm_clients.py backend\tests\test_browser_api.py
.\.venv\Scripts\ruff.exe check backend
node --check backend\app\static\app.js
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The browser UI is served by FastAPI from `backend/app/static/`. Main user pages are configured in `backend/app/static/index.html` and driven by `backend/app/static/app.js`.

## Change Discipline

- Keep AI suggestions separate from approved ontology exports.
- Never expose API keys in API responses, logs, traces, or saved-config listings.
- Update documentation when routes, environment variables, workflows, architecture, or setup change.
- Add or update tests for behavior changes.
- Preserve existing CLI commands, API routes, runtime database behavior, literature pipeline behavior, LLM configuration, candidate review workflow, and ODK/ROBOT exports unless the task explicitly requires otherwise.

## Data Flow Landmarks

- API routes: `backend/app/api/routes.py`
- Runtime settings and secret masking: `backend/app/services/runtime_config.py`
- Database models: `backend/app/models/db.py`
- Browser UI: `backend/app/static/index.html`, `backend/app/static/app.js`, `backend/app/static/styles.css`
- LLM providers: `backend/app/llm/presets.py`, `backend/app/llm/clients.py`
- Ontology tree extraction: `backend/app/ontology/local.py`
- Relation type catalogue: `backend/app/ontology/relations.py`
- Candidate review state: `CandidateTermRecord` in `backend/app/models/db.py`

