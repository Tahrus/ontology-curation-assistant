# UI Wireframe

## Candidate Dashboard

Filters:

- confidence
- source document
- review status
- relation type
- ontology match status

Columns:

```text
label | type | confidence | evidence count | possible match | review status
```

## Candidate Review Page

Left pane:

- source document metadata
- highlighted evidence quote
- surrounding paragraph
- page and section

Right pane:

- candidate label
- proposed definition
- synonyms
- proposed parent
- proposed relations
- ontology matches
- reviewer decision controls

Actions:

```text
approve | edit and approve | reject | duplicate | map to existing | needs more evidence | defer
```

## ODK Export Page

Shows:

- approved candidates ready for export
- target ODK template path
- generated TSV preview
- validation/build status
- Git branch and commit hash

