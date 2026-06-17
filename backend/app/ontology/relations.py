from __future__ import annotations

from typing import Any


RELATION_TYPES: list[dict[str, Any]] = [
    {
        "id": "RO:0002233",
        "label": "has input",
        "inverse": "input of",
        "description": "Relates a process to a material entity consumed or used by the process.",
        "expected_source_type": "process",
        "expected_target_type": "material entity",
    },
    {
        "id": "RO:0002234",
        "label": "has output",
        "inverse": "output of",
        "description": "Relates a process to an entity produced by the process.",
        "expected_source_type": "process",
        "expected_target_type": "material entity",
    },
    {
        "id": "RO:0000057",
        "label": "has participant",
        "inverse": "participates in",
        "description": "Relates a process to a continuant that participates in it.",
        "expected_source_type": "process",
        "expected_target_type": "continuant",
    },
    {
        "id": "BFO:0000051",
        "label": "has part",
        "inverse": "part of",
        "description": "Relates an entity to one of its parts.",
        "expected_source_type": "entity",
        "expected_target_type": "entity",
    },
    {
        "id": "BFO:0000050",
        "label": "part of",
        "inverse": "has part",
        "description": "Relates an entity to a larger entity it is part of.",
        "expected_source_type": "entity",
        "expected_target_type": "entity",
    },
    {
        "id": "IAO:0000417",
        "label": "is measurement of",
        "inverse": "has measurement datum",
        "description": "Relates a measurement datum to what it measures.",
        "expected_source_type": "measurement datum",
        "expected_target_type": "entity",
    },
    {
        "id": "IAO:0000416",
        "label": "has measurement datum",
        "inverse": "is measurement of",
        "description": "Relates an entity to a measurement datum about it.",
        "expected_source_type": "entity",
        "expected_target_type": "measurement datum",
    },
    {
        "id": "RO:0000053",
        "label": "has quality",
        "inverse": "quality of",
        "description": "Relates an entity to a quality that inheres in it.",
        "expected_source_type": "entity",
        "expected_target_type": "quality",
    },
    {
        "id": "OCA:has_process_parameter",
        "label": "has process parameter",
        "inverse": "process parameter of",
        "description": "Relates a process to a parameter reviewed for that process.",
        "expected_source_type": "process",
        "expected_target_type": "parameter",
    },
    {
        "id": "IAO:0000039",
        "label": "has unit",
        "inverse": "unit of",
        "description": "Relates a measurement datum or parameter to a unit.",
        "expected_source_type": "measurement datum",
        "expected_target_type": "unit",
    },
]


def relation_type_payload() -> dict[str, list[dict[str, Any]]]:
    return {"relation_types": RELATION_TYPES}
