# Meta-UI

Last updated: 2026-06-17

The browser UI is organized around project-level work without making every workflow fully project-aware yet.

## Navigation Groups

The top navigation labels are grouped by work area:

- Project Dashboard: active project metadata and app readiness.
- Project Management: project hierarchy, active selection, workspace paths, existing ontology projects, repository metadata.
- Literature: literature records, Markdown inspection, import controls, and project tags.
- Ontology: active-project ontology source status and ontology browser.
- Curation: candidate generation and candidate review.
- Curation Prompt, Suggestions, Evaluation: project-scoped prompt/review/evaluation tools already present in the app.
- LLM Settings: provider/API configuration and connection tests.
- Export / ODK: approved candidate downloads and ODK-oriented export status.

## Active Project Visibility

The active project appears in a persistent banner below the header and on the dashboard. The banner shows active project name, ontology ID, project type, and quick links to project details or project switching. Dashboard cards show name, ontology ID/prefix, project type, parent, child projects, workspace status, repository metadata, ontology/literature path statuses, and tagged-literature count.

The Dashboard shows a project hierarchy tree instead of the former meta-ontology graph. Project tiles represent ontology-development workspaces and parent/child project organization; they are not ontology classes, ontology relations, ontology imports, or curation meta-model nodes. Clicking a tile sets that project as active. The active tile is highlighted and the dashboard preview updates to the selected/active project.

The Ontology page is usable only downstream of the active project. Without an active project it shows a select-project message. After project selection, it refreshes to that project's ontology ID, base IRI, editable ontology path/status, built ontology path/status, ODK repository status, and selected ontology source.

Project-dependent sections now show a visible no-active-project blocker rather than silently implying global context. Literature, Ontology, Curation, and Export / ODK each explain that a project should be selected first. LLM Settings remain global.

## Boundaries

This Meta-UI work does not change graph rendering, candidate review, LLM provider configuration, literature PDF/Markdown processing, or ODK/ROBOT export behavior. Those workflows remain on their existing code paths.
