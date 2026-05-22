# API Sketch

The first API should support ingestion, candidate review, and ODK export.

## Health and Configuration

```text
GET /health
GET /api/config
```

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

