# Architecture

Ontology Curation Assistant is organized around a hard boundary between AI suggestions and ontology changes.

```text
literature -> parsing -> AI extraction -> candidate store -> human review -> approved export -> ODK build
```

## Components

- Ingestion: registers source documents and stores checksums.
- Parsing: converts PDFs, XML, HTML, and text into traceable text segments.
- Extraction: calls AI models with versioned prompts and structured schemas.
- Evidence: stores immutable source snippets and document locations.
- Review: tracks human validation decisions.
- Ontology matching: compares candidates to existing ontology terms.
- ODK integration: writes approved rows to ODK-compatible templates and runs configured build commands.
- Audit: records every suggestion, edit, export, and build event.

## Principle

The system can recommend. It cannot mutate the final ontology without human approval.

