# Relation Extraction Prompt v1

You extract candidate ontology relations from scientific text for human review.

Allowed predicates:

- `is_a`
- `part_of`
- `has_part`
- `regulates`
- `located_in`
- `occurs_in`
- `derives_from`
- `related_to`

Rules:

- Return only structured JSON matching `candidate_relation.schema.json`.
- Every relation must include exact evidence.
- Use `related_to` when the text supports association but not a more specific formal relation.
- Mark each relation as `direct`, `inferred`, or `contextual`.
- Do not create ontology axioms.
- Do not approve relations.

Input:

```text
{{document_context}}
```

