# ODK Integration

The assistant integrates with ODK through files, commands, and Git.

## Local ODK Home

Configured default:

```text
C:\Users\ge47vob\ontology-development-kit
```

This is the local ODK checkout/tooling location.

## Ontology Repository

Set `OCA_ONTOLOGY_REPO` to the actual ODK-managed ontology repository that should receive reviewed templates.

## Generated Files

Typical export targets:

```text
src/ontology/templates/ai_approved_terms.tsv
src/ontology/templates/ai_approved_relations.tsv
src/ontology/mappings/ai_approved_mappings.sssom.tsv
reports/ai-curation/batch-summary.md
reports/ai-curation/evidence-report.tsv
```

## Build Flow

1. Confirm all exported rows are human-approved.
2. Create or switch to an `ai-curation/` Git branch.
3. Write template files.
4. Run project-specific ODK targets such as `make test`.
5. Parse validation errors.
6. Commit generated files only after validation.
7. Optionally open a pull request.

## Error Reporting

ODK validation errors should be mapped back to candidate IDs and template rows whenever possible.

