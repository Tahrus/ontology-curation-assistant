# API Sketch

The first API should support ingestion, candidate review, and ODK export.

## Health and Configuration

```text
GET /health
GET /api/config
```

## Current CLI-Only Literature Source Workflow

Zotero metadata import and sync are currently exposed through CLI commands:

```text
oca zotero-import <metadata_file>
oca zotero-list
oca zotero-show <source_id>
oca zotero-link-documents <literature_dir>
oca zotero-config
oca zotero-sync
```

This workflow imports exported metadata into OCA's local database, can sync metadata from the Zotero Web API, and links already ingested documents conservatively. It does not read Zotero's internal database, download attachments, or write to Zotero.

## Future Endpoints

```text
POST /api/corpora
POST /api/documents/upload
POST /api/extraction-runs
GET /api/candidates
GET /api/candidates/{candidate_id}
PATCH /api/candidates/{candidate_id}/review
GET /api/relations
PATCH /api/relations/{relation_id}/review
POST /api/exports/odk
POST /api/odk/validate
POST /api/odk/build
GET /api/audit
```

## Safety Constraints

- Export endpoints must reject candidates that are not human-approved.
- Build endpoints should run on a Git branch, not directly on a main branch.
- API responses should expose evidence and provenance for all suggestions.
