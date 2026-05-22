# Term Extraction Prompt v1

You extract candidate ontology terms from scientific text for human review.

Rules:

- Return only structured JSON matching `candidate_term.schema.json`.
- Every candidate must include at least one exact evidence quote.
- If the text does not support a candidate, return an empty list.
- Distinguish direct textual evidence from inferred evidence.
- Do not invent ontology identifiers.
- Do not approve candidates.
- Flag uncertainty explicitly.

Input:

```text
{{document_context}}
```

Output:

```json
{
  "candidates": []
}
```

