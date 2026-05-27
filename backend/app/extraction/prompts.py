PROMPT_NAME = "term_extraction"
PROMPT_VERSION = "v1"
DEFAULT_CONTEXT_CHARS = 12000


def build_candidate_extraction_prompt(
    document_text: str,
    *,
    document_id: int,
    filename: str,
    chars: int = DEFAULT_CONTEXT_CHARS,
) -> str:
    """Build the curator-facing term extraction prompt for one source document."""
    bounded_text = document_text[:chars]
    return f"""You are assisting human ontology curators.

Extract candidate ontology class terms from scientific literature for human review.
Return only valid JSON. Do not include markdown fences or explanatory prose.

Focus on terms that could plausibly become ontology classes and are supported by exact source evidence.

Prefer:
- biochemical concepts
- molecular biology concepts
- protein chemistry concepts
- solvent interaction concepts
- thermodynamic concepts
- assay/reaction concepts
- terms supported by direct textual evidence

Explicitly exclude:
- author names
- affiliations/institutions
- journal names
- download headers
- bibliographic artifacts
- malformed PDF fragments
- generic phrases
- overly broad terms
- phrases not suitable as ontology classes

Each candidate must include:
- label
- proposed_definition
- synonyms
- proposed_parent
- confidence_score from 0.0 to 1.0
- evidence with exact quote(s)
- direct_or_inferred, one of: direct, inferred, contextual

Use this exact JSON shape:
{{
  "candidates": [
    {{
      "label": "preferential hydration",
      "proposed_definition": "A concise curator-facing definition supported by the text.",
      "synonyms": ["water of preferential hydration"],
      "proposed_parent": "protein-solvent interaction",
      "confidence_score": 0.92,
      "evidence": [
        {{
          "quoted_text": "Exact quote from the document.",
          "section_title": null,
          "page_number": null,
          "char_start": null,
          "char_end": null,
          "direct_or_inferred": "direct"
        }}
      ]
    }}
  ]
}}

If no suitable ontology candidates are supported, return:
{{"candidates": []}}

Source document id: {document_id}
Source filename: {filename}

Source text:
```text
{bounded_text}
```
"""
