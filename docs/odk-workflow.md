# ODK Workflow

ODK and ROBOT workflows are export and staging paths for approved content. They should not be triggered by LLM suggestion generation or graph-review proposals alone.

## Files

- ODK helpers: `backend/app/odk/`
- ODK diagnostics route: `POST /api/diagnostics/docker-odk` in `backend/app/api/routes.py`
- Browser diagnostics: Configuration page in `backend/app/static/index.html`
- Entry-generation and export tests: `backend/tests/test_entry_generation.py`

## Rules

- Only approved candidates are eligible for ODK/ROBOT-oriented export.
- The selected ontology file used for LLM suggestion context is read-only during suggestion generation.
- Non-dry-run ODK workflows require production mode checks.
- Docker setups should mount persistent data, literature, ontology, and ODK workspace paths rather than writing into the image layer.

Run diagnostics from Configuration > Docker / ODK Diagnostics before production export work.

