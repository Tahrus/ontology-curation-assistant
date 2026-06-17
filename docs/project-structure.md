# Project Structure

Last updated: 2026-06-17

This document describes the project-management scaffold in the Ontology Curation Assistant. It is metadata and UI structure only. It does not create ontology classes, build ODK repositories, route every workflow by project, edit graphs, or change ROBOT/ODK export behavior.

## What A Project Is

A project represents one ontology-development effort that can be selected as active in the browser. A project can be a planned ontology, a domain ontology, a module, an application ontology, or an existing ontology source represented as a node in the project hierarchy.

Stored project fields include:

- project ID, slug, name, active flag, and timestamps
- ontology ID/short name, ontology title, namespace/prefix, base IRI, and term ID prefix
- project type: `upper_bioprocess_ontology`, `domain_ontology`, `module`, `application_ontology`, or `existing_ontology_project`
- optional parent project ID
- short description and minimal scope notes
- workspace path, ODK repository path, editable ontology file path, built/released ontology file path, literature repository path, local Git repository path, and GitHub repository URL/path

Missing optional paths are reported as status warnings. They do not block conceptual project creation.

## Project Hierarchy

The project hierarchy represents ownership and planning relationships, not ontology subclass structure.

Example:

```text
Bioprocess Ontology
  Upstream Processing Ontology
    PREFER
```

`PREFER` can be represented as an `existing_ontology_project` with a parent project and local file/repository paths. This does not create ontology import semantics. It only records that the existing ontology source is part of the managed project landscape.

## Removed Import Placeholders

Dependency/import placeholders and external-reference placeholders are intentionally not part of the active project UI. Actual ontology import/dependency handling will be solved later during curation and ontology review, where the app has enough context about candidate terms, ontology files, imports, and curator decisions.

## Project Wizard

The browser Projects page uses a four-step wizard plus project cards and a detail panel:

1. Project identity: name, ontology ID, project type, parent project, base IRI, short description, and minimal scope notes.
2. Workspace paths: workspace/root folder and optional ODK/editable/built/literature paths.
3. Repository metadata: local Git repository path and GitHub repository URL/path.
4. Review and create: summary plus warnings for missing optional paths.

Detailed description and scope can be generated or refined later by the LLM based on the built ontology and curated content.

Project cards show active/inactive state, ontology ID, project type, parent, child count, workspace path, literature status, ontology status, and last modified date. `View project details` opens a detail panel with identity, hierarchy, path usage/status, and next-step guidance. `Edit project metadata` loads the current values into the wizard. `Set this project as active` changes the active project. `Create child project` starts a new wizard entry with the parent preselected.

## Base IRI

When an ontology ID is entered, the browser suggests:

```text
http://purl.obolibrary.org/obo/<ontology_id>.owl
```

The suggestion updates while the ontology ID changes only until the base IRI field is manually edited. After manual editing, later ontology ID changes preserve the curator's base IRI override. The backend validates that a provided base IRI looks like an IRI.

## Optional AI Assistance

The Projects page includes `Suggest project metadata with AI`. The curator enters a short idea and, when LLM settings are configured, the backend asks the configured LLM for a small JSON draft containing project name, ontology ID, project type, short description, base IRI, and minimal scope notes.

The draft only fills empty editable fields and reports suggestions for fields that already contain curator-entered values. It never creates a project automatically. If the LLM response is malformed or credentials/configuration are missing, the error is shown without clearing the wizard.

## Failed Save Behavior

Project creation and metadata edits preserve all entered field values when the backend rejects the request, such as duplicate ontology IDs, invalid base IRIs, invalid parent selections, or filesystem errors. The form resets only after a successful create/update or an explicit cancel/reset action.

Project errors are displayed with the failed operation, backend detail, likely cause, next action, and HTTP technical detail. Stack traces remain in developer tooling rather than normal UI messages.

## Active-Project Ontology Source

The browser Ontology page is downstream of the active project. With no active project, it shows a select-project warning and does not load global or stale ontology data. With an active project, it displays project metadata, path statuses, and the selected ontology source.

Source resolution prefers an existing built/released ontology file from `built_ontology_path`, then an existing editable ontology file from `editable_ontology_path`, and only then conventional project/ODK build locations. Missing optional paths are warnings.

## Literature Tags

Zotero-backed literature entries can carry explicit project tags. Tags can use project ontology IDs, slugs, or IDs, and untagged literature remains valid. The active project dashboard and project payload report how many literature entries are tagged to that project.

Repository-only Markdown entries are shown in the Literature UI but are not editable through this minimal tag editor yet.

## Intentionally Later

- Real ontology import/dependency handling.
- External reference ontology modeling.
- Project-specific literature routing.
- Project-specific candidate generation/review routing.
- Complete project-specific graph routing beyond the active browser ontology source/status and tree/term calls.
- Real ontology file creation.
- Automatic GitHub repository creation.
- ODK repository creation, build, test, or ROBOT command execution.
