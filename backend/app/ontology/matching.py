from dataclasses import dataclass


@dataclass(frozen=True)
class OntologyMatch:
    curie: str
    label: str
    match_type: str
    score: float


def exact_label_match(candidate_label: str, existing_terms: dict[str, str]) -> OntologyMatch | None:
    normalized = candidate_label.strip().casefold()
    for curie, label in existing_terms.items():
        if label.strip().casefold() == normalized:
            return OntologyMatch(curie=curie, label=label, match_type="exact_label", score=1.0)
    return None

