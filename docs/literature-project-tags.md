# Literature Project Tags

Last updated: 2026-06-17

Literature project tags let one shared literature repository support multiple ontology-development projects without duplicating papers or rewriting the PDF-to-Markdown pipeline.

## Storage

Project tags are stored on Zotero-backed `LiteratureSource` rows in `project_tags_json`. This is separate from Zotero/source `tags_json`, so curator project tags do not overwrite bibliography tags imported from Zotero.

Tags may reference:

- project ontology IDs, such as `ppo`
- project slugs
- project database IDs as strings

The dashboard count treats any of those identifiers as a match for the active project.

## UI

The Literature page shows a multi-select project tag control for Zotero-backed records. Saving tags calls:

```text
PATCH /api/zotero/entries/{source_id}/project-tags
```

Repository-only Markdown entries are still visible but are not tag-editable in this minimal implementation.

## Boundaries

Untagged literature remains valid. Tags do not change import, PDF conversion, Markdown generation, candidate extraction, or ontology export behavior yet.
