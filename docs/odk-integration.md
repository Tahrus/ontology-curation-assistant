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

For PPO, the expected ODK ontology source directory is typically:

```text
C:\Users\ge47vob\ontology-development-kit\target\ppo\src\ontology
```

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

## Existing Ontologies and Imports

Use existing ontologies in two different ways:

- Edit the project ontology only when the term belongs in the maintained ontology itself.
- Import external ontologies when they provide context, parents, mappings, or cross-references that should not be edited locally.

For an ODK project, place source/import files under the project's `src/ontology` tree according to that ontology's conventions. Common locations include:

```text
src/ontology/imports/
src/ontology/templates/
src/ontology/mappings/
```

Configure the project Makefile and ROBOT commands so imports are extracted, templates are applied, and mappings are merged in the intended order. The OCA-approved template output should remain a reviewed input file, such as:

```text
src/ontology/templates/ai_approved_terms.tsv
```

For PPO, after the ODK workflow/build succeeds, inspect the generated simplified ontology at a path similar to:

```text
target/ppo/src/ontology/ppo-simple.obo
```

This file is the ODK/ROBOT-built output after imports, templates, and project Make targets have been applied. It should be inspected or validated with the project `make test` target, ROBOT report commands, Protégé, or OBO tooling before any upload or pull request.

## Error Reporting

ODK validation errors should be mapped back to candidate IDs and template rows whenever possible.
