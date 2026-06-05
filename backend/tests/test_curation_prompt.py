import json
from pathlib import Path

import pytest

from backend.app.llm.curation import (
    DEFAULT_CURATION_PROMPT,
    CurationInputError,
    CurationResponseError,
    load_curation_inputs,
    run_curation_suggestion_workflow,
)
from backend.app.services.runtime_config import LlmRuntimeConfig


def llm_config() -> LlmRuntimeConfig:
    return LlmRuntimeConfig(
        provider="openai",
        api_key="secret-test-key",
        model="test-model",
        base_url="https://llm.example/v1",
    )


def write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    ontology = tmp_path / "ontology.obo"
    ontology.write_text(
        "format-version: 1.2\n\n[Term]\nid: TEST:0001\nname: existing protein term\n",
        encoding="utf-8",
    )
    literature = tmp_path / "combined_literature.md"
    literature.write_text(
        "# Combined Literature Markdown\n\nPreferential hydration supports protein stability.",
        encoding="utf-8",
    )
    return ontology, literature


def valid_response(label: str = "preferential hydration") -> str:
    return json.dumps(
        {
            "suggestions": [
                {
                    "suggestion_type": "new_class",
                    "proposed_label": label,
                    "existing_ontology_id": None,
                    "proposed_definition": "A protein-solvent enrichment process.",
                    "synonyms": [],
                    "parent_class": "TEST:0001",
                    "relations": [],
                    "source_literature_ids": ["lit-1"],
                    "supporting_quotes_or_summaries": ["Preferential hydration supports protein stability."],
                    "confidence": 0.88,
                    "rationale": "Supported by the supplied combined literature.",
                }
            ],
            "warnings": [],
        }
    )


def test_curation_input_validation_blocks_missing_or_empty_literature(tmp_path):
    ontology, literature = write_inputs(tmp_path)
    literature.unlink()

    with pytest.raises(CurationInputError, match="combined_literature.md was not found"):
        load_curation_inputs(
            prompt=DEFAULT_CURATION_PROMPT,
            ontology_path=ontology,
            literature_path=literature,
        )

    literature.write_text("", encoding="utf-8")
    with pytest.raises(CurationInputError, match="combined_literature.md is empty"):
        load_curation_inputs(
            prompt=DEFAULT_CURATION_PROMPT,
            ontology_path=ontology,
            literature_path=literature,
        )


def test_curation_input_validation_blocks_missing_or_invalid_ontology(tmp_path):
    _ontology, literature = write_inputs(tmp_path)

    with pytest.raises(CurationInputError, match="No existing ontology file is selected"):
        load_curation_inputs(
            prompt=DEFAULT_CURATION_PROMPT,
            ontology_path=None,
            literature_path=literature,
        )

    missing = tmp_path / "missing.obo"
    with pytest.raises(CurationInputError, match="Selected ontology file was not found"):
        load_curation_inputs(
            prompt=DEFAULT_CURATION_PROMPT,
            ontology_path=missing,
            literature_path=literature,
        )

    owl = tmp_path / "ontology.owl"
    owl.write_text("<rdf></rdf>", encoding="utf-8")
    with pytest.raises(CurationInputError, match="must be an .obo"):
        load_curation_inputs(
            prompt=DEFAULT_CURATION_PROMPT,
            ontology_path=owl,
            literature_path=literature,
        )


def test_curation_request_includes_saved_prompt_obo_and_combined_literature_and_stores_response(tmp_path):
    ontology, literature = write_inputs(tmp_path)
    prompts = []
    before = ontology.read_text(encoding="utf-8")

    def caller(prompt, config):
        prompts.append(prompt)
        return valid_response()

    result = run_curation_suggestion_workflow(
        prompt="Saved custom curation prompt.",
        ontology_path=ontology,
        literature_path=literature,
        config=llm_config(),
        output_dir=tmp_path / "trace",
        caller=caller,
    )

    request_text = result.request_path.read_text(encoding="utf-8")
    response = json.loads(result.response_path.read_text(encoding="utf-8"))

    assert result.ok
    assert result.suggestion_count == 1
    assert "# CURATION PROMPT" in prompts[0]
    assert "Saved custom curation prompt." in prompts[0]
    assert "# CURRENT ONTOLOGY OBO" in prompts[0]
    assert "id: TEST:0001" in prompts[0]
    assert "# LITERATURE EVIDENCE: combined_literature.md" in prompts[0]
    assert "Preferential hydration supports protein stability." in prompts[0]
    assert "Return valid JSON only" in prompts[0]
    assert response["suggestions"][0]["proposed_label"] == "preferential hydration"
    assert "secret-test-key" not in request_text
    assert ontology.read_text(encoding="utf-8") == before


def test_curation_invalid_json_response_is_reported_and_raw_response_stored(tmp_path):
    ontology, literature = write_inputs(tmp_path)

    with pytest.raises(CurationResponseError, match="not valid JSON"):
        run_curation_suggestion_workflow(
            prompt=DEFAULT_CURATION_PROMPT,
            ontology_path=ontology,
            literature_path=literature,
            config=llm_config(),
            output_dir=tmp_path / "trace",
            caller=lambda prompt, config: "not-json",
        )

    assert (tmp_path / "trace" / "raw_response.txt").read_text(encoding="utf-8") == "not-json"
    assert "secret-test-key" not in (tmp_path / "trace" / "request.json").read_text(encoding="utf-8")


def test_curation_oversized_literature_is_chunked_without_truncation(tmp_path):
    ontology, literature = write_inputs(tmp_path)
    literature.write_text("A" * 1500 + "\n\n" + "B" * 1500, encoding="utf-8")
    prompts = []

    result = run_curation_suggestion_workflow(
        prompt="Prompt.",
        ontology_path=ontology,
        literature_path=literature,
        config=llm_config(),
        output_dir=tmp_path / "trace",
        max_context_chars=2500,
        caller=lambda prompt, config: prompts.append(prompt) or valid_response("chunk term"),
    )

    assert result.oversized
    assert result.chunk_count > 1
    assert result.suggestion_count == result.chunk_count
    assert any("A" * 200 in prompt for prompt in prompts)
    assert any("B" * 200 in prompt for prompt in prompts)
