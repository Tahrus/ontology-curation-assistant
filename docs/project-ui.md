# Project UI

Last updated: 2026-06-17

The Projects page at `/projects` is the main place to create, inspect, edit, and select ontology-development projects. Projects are metadata/workspace records. They do not create ontology classes, GitHub repositories, ODK repositories, or production ontology changes.

## Where Projects Are Shown

- The persistent active-project banner appears below the main navigation on every page.
- The Dashboard shows active-project readiness cards and a project hierarchy tree.
- The Projects page shows the project wizard, selected project details, active project summary, and all existing projects as cards.

Each project card shows name, ontology ID, project type, active/inactive state, parent, child count, workspace path, literature path status, ontology path status, and last modified time when available.

## Dashboard Project Hierarchy

The Dashboard replaces the former meta-ontology graph with a project hierarchy tree. Root projects appear at the top, child/domain projects are indented underneath their parent, and the active project is highlighted.

This dashboard tree is a project organization view. It is not an ontology class hierarchy, ontology relation graph, meta-ontology graph, or import/dependency graph.

Clicking a project tile sets that project as active for work and updates the active-project banner plus the compact dashboard preview. Tile buttons provide explicit actions for `Work on this project`, `View details`, `Edit metadata`, and `Create child project`; clicking those buttons does not accidentally activate the tile unless the button is the activation action.

If no projects exist, the Dashboard shows `No projects exist yet. Create a project to start ontology curation.` with a `Create first project` link. If projects exist but no project is active, it shows `No active project selected. Click a project tile to work on it.`

## Creating A Project

Use the project wizard on `/projects`.

1. Enter project identity fields such as name, ontology ID, project type, base IRI, description, and scope notes.
2. Add optional workspace, ODK, editable ontology, built ontology, and literature paths.
3. Add optional local Git and GitHub metadata.
4. Review warnings and click `Create project`.

`Suggest project metadata with AI` can fill empty wizard fields from a short idea. It never creates the project automatically.

After a successful create, the new project is selected, the detail panel shows a next-step guide, and the banner updates.

## Editing Metadata

Use `Edit project metadata` from a project card or the detail panel. The wizard is prefilled with the current project metadata.

Editable fields include project name, ontology ID, project type, parent project, base IRI, description, scope notes, workspace path, ODK repository path, editable ontology file path, built ontology file path, literature repository path, local Git repository path, and GitHub URL/path.

The parent selector excludes the project itself and its descendants. The backend still validates self-parent and circular-parent changes.

Failed saves preserve all entered values. The error message identifies the operation, details, likely cause, next action, and technical HTTP detail.

## Active Project Meaning

The active project is the current project context for project-aware UI areas. The banner shows the active project name, ontology ID, project type, and quick links to details or project switching.

If no active project is selected, project-dependent sections show a blocker message with a link back to Projects. LLM settings remain global.

Project-dependent sections currently include:

- Literature project tagging and later project-scoped evidence context.
- Ontology source status and ontology browser.
- Candidate generation and review context.
- Export / ODK readiness.

## Details And Next Actions

The project detail panel shows identity, hierarchy, path/status cards, descriptions of what each path is used for, and contextual next steps. Upper-level projects suggest reviewing metadata, configuring paths, adding child/domain projects, importing/tagging literature, and later generating/reviewing candidates. Child/domain projects suggest confirming parent, configuring source paths, tagging literature, and later candidate review.

Implemented actions include:

- Edit project metadata.
- Set project as active.
- Create child project.
- Open literature section.
- Open ontology browser when the selected project is active.

Planned or unsupported actions are disabled instead of pretending to work, such as opening local filesystem paths from the browser.

## Error Display

Project-related errors are shown in user-readable form:

- Operation that failed.
- Backend detail.
- Likely cause.
- Suggested next action.
- Technical HTTP detail.

Stack traces are not shown in the normal UI; technical errors are still written to the browser console.

## Manual Verification

1. Create a project and confirm it appears in the project list and active-project banner.
2. Click `View project details` and confirm identity, hierarchy, paths/statuses, and next actions are visible.
3. Click `Edit project metadata`, confirm the form is prefilled, save a metadata change, and confirm the detail panel/dashboard updates.
4. Trigger a failed edit, for example a duplicate ontology ID or invalid base IRI, and confirm the form values remain visible.
5. Click `Set this project as active` on another project and confirm the banner updates.
6. Create at least two projects with a parent-child relationship, open the Dashboard, and confirm the meta-ontology graph is gone.
7. Confirm project tiles are visible and the parent-child structure is shown with indentation/connectors.
8. Click a child project tile and confirm it becomes active, the active-project banner updates, and the dashboard preview updates.
9. Confirm `View details` and `Edit metadata` buttons navigate to Project Management without accidental tile activation.
10. Visit Ontology, Literature, Curation, or Export with no active project and confirm a clear project-required message appears.
11. Create a child project from an existing project and confirm the parent field is preselected.

## Intentionally Not Implemented

- Deleting or archiving projects.
- Creating ontology classes/files automatically.
- Creating GitHub repositories.
- Running ODK builds/tests.
- Rewriting literature import, candidate review, graph rendering, or ODK/ROBOT export workflows.
