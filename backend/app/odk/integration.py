from dataclasses import dataclass
import csv
import json
import logging
from pathlib import Path
from typing import TextIO

from backend.app.config import get_settings
from backend.app.models.db import CandidateTermRecord


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OdkProjectConfig:
    repo_path: Path
    template_dir: str = "src/ontology/templates"
    default_template_file: str = "ai_approved_terms.tsv"


def preview_export_path(config: OdkProjectConfig) -> Path:
    """Return the target ROBOT template path for approved AI-assisted terms."""
    return config.repo_path / config.template_dir / config.default_template_file


def build_command_candidates() -> list[str]:
    """Project-specific ODK repos may expose different Make targets."""
    return ["make test", "make prepare_release"]


def default_ppo_odk_ontology_path() -> Path:
    """Return the configured PPO ODK ontology working directory."""
    return get_settings().ppo_odk_ontology_path


def validate_ppo_odk_ontology_path(path: Path | None = None) -> Path:
    """Validate that the PPO ODK ontology path exists before generation work starts."""
    target = Path(path or default_ppo_odk_ontology_path())
    if not target.exists():
        raise FileNotFoundError(f"PPO ODK ontology path does not exist: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"PPO ODK ontology path is not a directory: {target}")
    return target


def stage_generated_ontology_artifact(
    relative_path: str,
    content: str,
    *,
    ontology_path: Path | None = None,
) -> Path:
    """Write a generated ontology artifact under the configured PPO ODK ontology path."""
    root = validate_ppo_odk_ontology_path(ontology_path)
    output_path = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in output_path.parents and output_path != root_resolved:
        raise ValueError("Generated ontology artifact must stay under the PPO ODK ontology path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    LOGGER.info("Staged generated ontology artifact at %s", output_path)
    return output_path


def write_robot_template(candidates: list[CandidateTermRecord], output: TextIO) -> None:
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow([
        "ID",
        "LABEL",
        "TYPE",
        "definition",
        "parent",
        "synonyms",
        "xref",
        "notes",
        "curator_decision",
        "selected_ols_match",
        "selected_local_match",
        "source_document_id",
        "evidence",
    ])
    writer.writerow([
        "ID",
        "A rdfs:label",
        "TYPE",
        "A IAO:0000115",
        "SC %",
        "A oboInOwl:hasExactSynonym",
        "A oboInOwl:hasDbXref",
        "A rdfs:comment",
        "",
        "",
        "",
        "",
        "",
    ])

    for candidate in candidates:
        synonyms = "; ".join(json.loads(candidate.synonyms_json or "[]"))
        mappings = json.loads(candidate.mappings_json or "[]")
        selected = json.loads(candidate.selected_ols_json) if candidate.selected_ols_json else None
        selected_local = json.loads(candidate.selected_local_json) if candidate.selected_local_json else None
        evidence = json.loads(candidate.evidence_json or "[]")
        xrefs = "; ".join(str(item) for item in mappings)
        if selected:
            xrefs = "; ".join(filter(None, [xrefs, selected.get("term_id") or selected.get("iri")]))

        writer.writerow(
            [
                candidate.candidate_id,
                candidate.label,
                "owl:Class",
                candidate.proposed_definition or "",
                candidate.proposed_parent or "",
                synonyms,
                xrefs,
                candidate.curator_rationale or "",
                candidate.curator_decision,
                selected.get("iri", "") if selected else "",
                selected_local.get("iri", "") if selected_local else "",
                str(candidate.document_id),
                candidate.source_evidence or (evidence[0].get("quoted_text", "") if evidence else ""),
            ]
        )


def write_candidate_tsv(candidates: list[CandidateTermRecord], output: TextIO) -> None:
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(
        [
            "candidate_id",
            "label",
            "definition",
            "status",
            "confidence",
            "parent",
            "selected_ols_label",
            "selected_ols_ontology",
            "selected_ols_iri",
            "selected_local_label",
            "selected_local_iri",
            "curator_decision",
            "source_document_id",
            "evidence",
            "rationale",
        ]
    )
    for candidate in candidates:
        selected = json.loads(candidate.selected_ols_json) if candidate.selected_ols_json else {}
        selected_local = json.loads(candidate.selected_local_json) if candidate.selected_local_json else {}
        evidence = json.loads(candidate.evidence_json or "[]")
        writer.writerow(
            [
                candidate.candidate_id,
                candidate.label,
                candidate.proposed_definition or "",
                candidate.review_status,
                f"{candidate.confidence_score:.3f}",
                candidate.proposed_parent or "",
                selected.get("label", ""),
                selected.get("ontology_id", ""),
                selected.get("iri", ""),
                selected_local.get("label", ""),
                selected_local.get("iri", ""),
                candidate.curator_decision,
                candidate.document_id,
                candidate.source_evidence or (evidence[0].get("quoted_text", "") if evidence else ""),
                candidate.curator_rationale or "",
            ]
        )
