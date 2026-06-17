# Project UI Fix Notes

Last updated: 2026-06-17

## Active Code Paths

- Project creation wizard frontend: `backend/app/static/index.html` (`#project-create-form`) and `backend/app/static/app.js` submit listener on `#project-create-form`.
- Backend project creation endpoint: `backend/app/api/routes.py`, `create_project_endpoint()`, `POST /api/projects`.
- AI project metadata frontend call: `backend/app/static/app.js` click listener on `#project-ai-suggest`, calling `POST /api/projects/suggest-metadata`.
- AI project metadata backend endpoint: `backend/app/api/routes.py`, `suggest_project_metadata()`.
- LLM helper/provider path: `llm_config(session)` plus `generate_text()` from `backend.app.llm.clients`, the same configured provider path used by the LLM connection test.
- Active project selection storage: `backend/app/projects.py`, `select_project()`, stored in the `projects.active` database flag and surfaced by `GET /api/projects`.
- Ontology section frontend: `backend/app/static/index.html` (`#ontology-section`) and `backend/app/static/app.js` (`loadOntologyStatus()`, `loadOntologyTerms()`, `renderOntologyTree()`).
- Backend ontology source/status endpoint used by the Ontology section: `backend/app/api/routes.py`, `ontology_status()`, `GET /api/ontology/status`.

## Behavior

`Suggest project metadata with AI` sends the curator's short idea to the configured LLM and asks for JSON metadata. The backend accepts strict JSON, fenced JSON, or JSON embedded in short text. If parsing or the LLM call fails, the endpoint returns a controlled error and the frontend leaves all form fields untouched.

Project creation and editing only call `resetProjectForm()` after the backend successfully creates or updates a project. Validation or backend errors are shown above the form, relevant identity errors return the wizard to the first step, and existing field values remain visible for correction.

The Ontology page now reads from the active project. With no active project it shows `Select or create a project before working with ontology files.` and does not load global/stale ontology terms or trees. With an active project, the page shows the project name, ontology ID, base IRI, editable ontology path/status, built ontology path/status, ODK repository path/status, selected source, and warnings for missing files.

Source resolution prefers the active project's existing built/released ontology file, then the active project's existing editable ontology file. If neither exists, the page reports `No ontology file configured for this project.` It does not silently fall back to unrelated global ontology settings.

## Manual Checks

1. Open `/projects`, enter a short idea, click `Suggest project metadata with AI`, and confirm empty fields fill or a readable LLM/configuration error appears without clearing the form.
2. Create a project with an invalid base IRI or duplicate ontology ID. Confirm the error appears and all entered values remain in the wizard.
3. Start with no active project and open `/ontology`. Confirm only the select-project warning and inactive ontology controls are shown.
4. Select a project with configured ontology paths, open `/ontology`, and confirm the summary cards show that project's ontology metadata and source status.
5. Switch to a different active project and confirm `/ontology` refreshes to the new project instead of showing the previous source.

## Known Limitations

- The legacy global ontology scan/select/index endpoints remain for compatibility and tests, but the browser Ontology page no longer uses them as its source of truth.
- Project metadata AI suggestions propose or fill fields only; they never create a project automatically.
- Missing optional project paths are warnings. They do not create ontology files or ODK repositories.
