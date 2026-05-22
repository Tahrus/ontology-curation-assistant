# AI Behavior Policy

The AI component is a suggestion engine.

## Required

- Every suggestion includes evidence and provenance.
- Direct evidence and inferred evidence are labeled separately.
- Uncertainty is explicit.
- Prompts, model names, model versions, and extraction settings are stored.
- Raw model output is preserved for reproducibility.

## Forbidden

- No direct edits to final ontology files.
- No export of unreviewed content.
- No invented citations or ontology IDs.
- No overwriting human-approved content.
- No silent merging of candidates.

## Human Approval Gate

The review workflow is the authority. Confidence scores prioritize review; they do not approve content.

