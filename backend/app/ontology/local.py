from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


SUPPORTED_ONTOLOGY_SUFFIXES = {".owl", ".rdf", ".ttl", ".obo", ".tsv"}


@dataclass(frozen=True)
class OntologyFile:
    path: str
    name: str
    suffix: str
    size_bytes: int
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LocalOntologyTerm:
    term_id: str
    iri: str
    label: str
    definition: str | None = None
    synonyms: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    relations: list[dict[str, str]] = field(default_factory=list)
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scan_ontology_folder(folder: Path) -> dict[str, Any]:
    if not folder.exists():
        return {
            "path": str(folder),
            "exists": False,
            "readable": False,
            "files": [],
            "message": "Ontology folder does not exist.",
        }
    if not folder.is_dir():
        return {
            "path": str(folder),
            "exists": True,
            "readable": False,
            "files": [],
            "message": "Configured ontology path is not a folder.",
        }

    files = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_ONTOLOGY_SUFFIXES:
            continue
        files.append(
            OntologyFile(
                path=str(path.resolve()),
                name=path.name,
                suffix=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                kind="robot_template" if path.suffix.lower() == ".tsv" else "ontology",
            ).to_dict()
        )

    return {
        "path": str(folder),
        "exists": True,
        "readable": True,
        "files": files,
        "message": f"Detected {len(files)} supported ontology files.",
    }


def index_ontology_file(path: Path, *, max_terms: int | None = None) -> list[LocalOntologyTerm]:
    suffix = path.suffix.lower()
    if suffix in {".owl", ".rdf", ".ttl"}:
        return _index_rdf(path, max_terms=max_terms)
    if suffix == ".obo":
        return _index_obo(path, max_terms=max_terms)
    if suffix == ".tsv":
        return _index_tsv(path, max_terms=max_terms)
    raise ValueError(f"Unsupported ontology file type: {suffix}")


def search_terms(terms: list[LocalOntologyTerm], query: str, *, limit: int = 50) -> list[LocalOntologyTerm]:
    normalized = _normalize(query)
    if not normalized:
        return terms[:limit]
    scored = [
        (local_match_score(query, term.label, term.synonyms), term)
        for term in terms
    ]
    return [term for score, term in sorted(scored, key=lambda item: item[0], reverse=True) if score > 0.35][:limit]


def local_match_score(label: str, existing_label: str, synonyms: list[str] | None = None) -> float:
    values = [existing_label, *(synonyms or [])]
    normalized = _normalize(label)
    best = 0.0
    for value in values:
        candidate = _normalize(value)
        if not normalized or not candidate:
            continue
        if normalized == candidate:
            return 1.0
        if normalized in candidate or candidate in normalized:
            best = max(best, 0.85)
        best = max(best, round(SequenceMatcher(None, normalized, candidate).ratio(), 3))
    return best


def match_local_terms(
    label: str,
    synonyms: list[str],
    terms: list[LocalOntologyTerm],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    labels = [label, *synonyms]
    matches = []
    for term in terms:
        score = max(local_match_score(value, term.label, term.synonyms) for value in labels)
        if score <= 0.35:
            continue
        payload = term.to_dict()
        payload["score"] = score
        payload["match_type"] = "exact_or_synonym" if score >= 0.99 else "label_similarity"
        matches.append(payload)
    return sorted(matches, key=lambda item: item["score"], reverse=True)[:limit]


def ontology_tree_payload(
    terms: list[LocalOntologyTerm],
    *,
    root_id: str | None = None,
    depth_limit: int = 4,
    max_children: int = 80,
    query: str | None = None,
) -> dict[str, Any]:
    """Build a collapsible parent-child hierarchy payload for the browser."""
    by_id = {term.term_id or term.iri: term for term in terms}
    children_by_parent: dict[str, list[str]] = {}
    child_ids: set[str] = set()
    hierarchy_edges: list[dict[str, Any]] = []
    relation_edges: list[dict[str, Any]] = []
    warnings: list[str] = []
    for term in terms:
        child_id = term.term_id or term.iri
        for parent in term.parents or []:
            parent_id = str(parent)
            children_by_parent.setdefault(parent_id, []).append(child_id)
            child_ids.add(child_id)
            hierarchy_edges.append(
                {
                    "id": f"{parent_id}->{child_id}",
                    "source": parent_id,
                    "target": child_id,
                    "relation": "is_a",
                    "edgeType": "hierarchy",
                    "relation_type": "subClassOf",
                    "relation_label": "subClassOf",
                    "hierarchical": True,
                }
            )
        for relation in term.relations or []:
            target = relation.get("target")
            relation_type = relation.get("relation_type") or relation.get("type") or "related_to"
            if not target:
                warnings.append(f"Skipped relation from {child_id} without a target.")
                continue
            relation_edges.append(
                {
                    "id": f"{child_id}-{relation_type}->{target}",
                    "source": child_id,
                    "target": target,
                    "relation": relation.get("relation_label") or relation_type,
                    "edgeType": "semantic",
                    "relation_type": relation_type,
                    "relation_label": relation.get("relation_label") or relation_type,
                    "hierarchical": False,
                }
            )

    roots = [term.term_id or term.iri for term in terms if (term.term_id or term.iri) not in child_ids]
    if not roots and terms:
        roots = [terms[0].term_id or terms[0].iri]
    if root_id:
        roots = [root_id]
    if query:
        matched = search_terms(terms, query, limit=1)
        if matched:
            roots = [matched[0].term_id or matched[0].iri]

    def node_for(term_id: str, depth: int, seen: set[str]) -> dict[str, Any]:
        term = by_id.get(term_id)
        children = sorted(children_by_parent.get(term_id, []), key=lambda item: by_id.get(item).label if by_id.get(item) else item)
        visible_children = [] if depth >= depth_limit else [
            node_for(child_id, depth + 1, seen | {term_id})
            for child_id in children[:max_children]
            if child_id not in seen
        ]
        return {
            "id": term_id,
            "label": term.label if term else term_id,
            "definition": term.definition if term else None,
            "parents": term.parents if term else [],
            "children_ids": children,
            "relations": term.relations if term else [],
            "source_file": term.source_file if term else None,
            "child_count": len(children),
            "children_truncated": max(0, len(children) - len(visible_children)),
            "children": visible_children,
        }

    roots_payload = [node_for(term_id, 0, set()) for term_id in roots[:max_children]]
    return {
        "nodes": [
            {
                "id": term.term_id or term.iri,
                "label": term.label,
                "definition": term.definition,
                "synonyms": term.synonyms,
                "parent_ids": term.parents,
                "child_ids": sorted(children_by_parent.get(term.term_id or term.iri, [])),
                "relations": term.relations,
                "source_ontology": term.source_file,
                "source_file": term.source_file,
            }
            for term in terms
        ],
        "hierarchy_edges": hierarchy_edges,
        "relation_edges": relation_edges,
        "roots": roots_payload,
        "root_ids": roots,
        "root_count": len(roots),
        "term_count": len(terms),
        "depth_limit": depth_limit,
        "max_children": max_children,
        "query": query,
        "metadata": {
            "source_files": sorted({term.source_file for term in terms if term.source_file}),
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "warnings": warnings,
        },
    }


def _index_rdf(path: Path, *, max_terms: int | None) -> list[LocalOntologyTerm]:
    from rdflib import Graph, Literal, OWL, RDF, RDFS, URIRef

    graph = Graph()
    graph.parse(path)

    definition_predicates = [
        URIRef("http://purl.obolibrary.org/obo/IAO_0000115"),
        URIRef("http://www.w3.org/2004/02/skos/core#definition"),
    ]
    synonym_predicates = [
        URIRef("http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"),
        URIRef("http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym"),
    ]
    ignored_relation_predicates = {RDF.type, RDFS.label, RDFS.subClassOf, *definition_predicates, *synonym_predicates}
    subjects = set(graph.subjects(RDF.type, OWL.Class)) | set(graph.subjects(RDFS.label, None))
    terms = []
    for subject in sorted(subjects, key=str):
        if not isinstance(subject, URIRef):
            continue
        label = _first_literal(graph.objects(subject, RDFS.label))
        if not label:
            continue
        definitions = []
        for predicate in definition_predicates:
            definitions.extend(str(value) for value in graph.objects(subject, predicate) if isinstance(value, Literal))
        synonyms = []
        for predicate in synonym_predicates:
            synonyms.extend(str(value) for value in graph.objects(subject, predicate) if isinstance(value, Literal))
        parents = [
            _term_id(str(parent))
            for parent in graph.objects(subject, RDFS.subClassOf)
            if isinstance(parent, URIRef)
        ]
        relations = [
            {
                "relation_type": _term_id(str(predicate)),
                "relation_label": _term_id(str(predicate)),
                "target": _term_id(str(value)),
            }
            for predicate, value in graph.predicate_objects(subject)
            if predicate not in ignored_relation_predicates and isinstance(value, URIRef)
        ]
        terms.append(
            LocalOntologyTerm(
                term_id=_term_id(str(subject)),
                iri=str(subject),
                label=label,
                definition=definitions[0] if definitions else None,
                synonyms=synonyms,
                parents=parents,
                relations=relations,
                source_file=str(path),
            )
        )
        if max_terms is not None and len(terms) >= max_terms:
            break
    return terms


def _index_obo(path: Path, *, max_terms: int | None) -> list[LocalOntologyTerm]:
    terms = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line == "[Term]":
            if current and current.get("id") and current.get("name"):
                terms.append(_obo_term(current, path))
                if max_terms is not None and len(terms) >= max_terms:
                    return terms
            current = {"synonyms": [], "parents": [], "relations": []}
            continue
        if current is None or not line or line.startswith("!"):
            continue
        if line.startswith("id: "):
            current["id"] = line[4:].strip()
        elif line.startswith("name: "):
            current["name"] = line[6:].strip()
        elif line.startswith("def: "):
            current["definition"] = line[5:].strip().strip('"')
        elif line.startswith("synonym: "):
            current["synonyms"].append(line[9:].split('"')[1] if '"' in line else line[9:])
        elif line.startswith("is_a: "):
            current["parents"].append(line[6:].split()[0])
        elif line.startswith("relationship: "):
            parts = line[14:].split("!", 1)[0].split()
            if len(parts) >= 2:
                current["relations"].append(
                    {
                        "relation_type": parts[0],
                        "relation_label": parts[0],
                        "target": parts[1],
                    }
                )
    if current and current.get("id") and current.get("name"):
        terms.append(_obo_term(current, path))
    return terms


def _index_tsv(path: Path, *, max_terms: int | None) -> list[LocalOntologyTerm]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    terms = []
    for row in rows:
        label = _pick(row, ["LABEL", "label", "rdfs:label", "A rdfs:label"])
        if not label or label.startswith("A "):
            continue
        term_id = _pick(row, ["ID", "id", "term_id"]) or label
        synonyms = _split_multi(_pick(row, ["synonyms", "SYNONYMS", "A oboInOwl:hasExactSynonym"]))
        relations = _relations_from_tsv_row(row)
        terms.append(
            LocalOntologyTerm(
                term_id=term_id,
                iri=term_id,
                label=label,
                definition=_pick(row, ["definition", "DEFINITION", "A IAO:0000115"]),
                synonyms=synonyms,
                parents=_split_multi(_pick(row, ["parent", "PARENT", "SC %"])),
                relations=relations,
                source_file=str(path),
            )
        )
        if max_terms is not None and len(terms) >= max_terms:
            break
    return terms


def _obo_term(values: dict[str, Any], path: Path) -> LocalOntologyTerm:
    return LocalOntologyTerm(
        term_id=values["id"],
        iri=values["id"],
        label=values["name"],
        definition=values.get("definition"),
        synonyms=values.get("synonyms", []),
        parents=values.get("parents", []),
        relations=values.get("relations", []),
        source_file=str(path),
    )


def _first_literal(values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _term_id(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _pick(row: dict[str, str | None], keys: list[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value:
            return value.strip()
    return None


def _split_multi(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace("|", ";").split(";") if item.strip()]


def _relations_from_tsv_row(row: dict[str, str | None]) -> list[dict[str, str]]:
    relations = []
    relation_type = _pick(row, ["relation", "RELATION", "relationship", "RELATION_TYPE"])
    target = _pick(row, ["target", "TARGET", "relation_target", "RELATION_TARGET"])
    if relation_type and target:
        relations.append(
            {
                "relation_type": relation_type,
                "relation_label": relation_type,
                "target": target,
            }
        )
    return relations
