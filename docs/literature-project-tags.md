# Literature Project Tags

Last updated: 2026-06-25

Literature project tags let one shared literature repository support multiple ontology-development projects without duplicating papers or rewriting the PDF-to-Markdown pipeline.

## Storage

Project tags are stored on Zotero-backed `LiteratureSource` rows and staged/curated canonical literature metadata in `project_tags_json` or `project_tags`. This is separate from Zotero/source `tags_json`, so curator project tags do not overwrite bibliography tags imported from Zotero.

Each project has exactly one canonical project tag:

- the project `ontology_id`, such as `ppo`

Older aliases such as project slug, database ID, or project name are accepted at update time and normalized to the canonical tag. When aliases are encountered, they are preserved as legacy metadata rather than silently discarded.

## UI

The Literature page shows project tags as compact button-style pills with `aria-pressed`. Saving tags calls the generic endpoint:

```text
POST /api/literature/{item_id}/tags
```

The older Zotero endpoint remains compatible:

```text
PATCH /api/zotero/entries/{source_id}/project-tags
```

The literature overview can filter by one or more active project-tag pills.

## Boundaries

Untagged literature remains valid. Tags do not change provider selection, PDF conversion, Markdown generation, candidate extraction, or ontology export behavior directly; they scope review/filtering and project association.
