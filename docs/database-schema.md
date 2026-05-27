# Database Schema

The production database should be implemented with SQLAlchemy and Alembic.

## Core Tables

```text
documents
literature_sources
document_segments
extraction_runs
candidate_terms
candidate_synonyms
candidate_relations
evidence
ontology_matches
review_decisions
approved_ontology_entries
audit_events
odk_exports
odk_builds
```

## Important Relationships

- A literature source stores upstream bibliographic metadata, currently from offline Zotero/Better BibTeX-style exports or metadata-only Zotero Web API sync.
- A document may link to one literature source.
- A document has many document segments.
- An extraction run has many candidate terms and relations.
- A candidate term has many evidence records and synonyms.
- A candidate relation links a subject candidate, predicate, object candidate or existing ontology term, and evidence.
- A review decision records every human action.
- An ODK export includes only approved terms and relations.
- An ODK build belongs to an export and stores logs, status, branch, and commit hash.

## Review Status Rule

Only `approved` and `approved_with_edits` are exportable.
