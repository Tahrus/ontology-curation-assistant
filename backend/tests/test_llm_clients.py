import pytest

from backend.app.llm.clients import (
    GeminiLLMClient,
    LlmClientError,
    create_llm_client,
    estimate_input_size,
    provider_catalog,
    test_llm_connection as run_llm_connection_test,
)
import backend.app.llm.clients as clients
from backend.app.llm.presets import normalize_provider_id
from backend.app.services.runtime_config import LlmRuntimeConfig


def test_provider_preset_catalog_contains_defaults():
    catalog = provider_catalog()
    gemini = next(item for item in catalog["providers"] if item["id"] == "gemini")
    openai = next(item for item in catalog["providers"] if item["id"] == "openai")

    assert gemini["default_model"] == "gemini-2.5-flash"
    assert "GEMINI_API_KEY" in gemini["api_key_env_vars"]
    assert openai["default_model"] == "gpt-4.1-mini"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("gemini", "gemini"),
        ("google", "gemini"),
        ("google_gemini", "gemini"),
        ("google-ai", "gemini"),
        ("Google Gemini", "gemini"),
        ("Gemini API", "gemini"),
        ("google_ai", "gemini"),
        ("OpenAI", "openai"),
        ("ChatGPT", "openai"),
        ("openai-compatible", "openai-compatible"),
        ("Custom / OpenAI-compatible", "openai-compatible"),
        ("Anthropic", "anthropic"),
        ("Claude", "anthropic"),
    ],
)
def test_provider_normalization_accepts_ui_and_cli_aliases(provider, expected):
    assert normalize_provider_id(provider) == expected


def test_llm_connection_reports_missing_api_key():
    result = run_llm_connection_test(LlmRuntimeConfig(provider="gemini", model="gemini-2.5-flash"))

    assert result.ok is False
    assert result.status == "missing_api_key"
    assert result.api_key_found is False
    assert result.provider_key == "gemini"


def test_llm_connection_reports_mocked_success_with_key_source(monkeypatch):
    monkeypatch.setattr(
        clients,
        "generate_text",
        lambda prompt, system_prompt, config, json_mode=False: clients.LlmTextResult(
            text=(
                '{"answer":"understood","sample_count":{"value":42,"ontology_term_id":"OCA_TEST:0000003","ontology_term_label":"sample count"},"ph":{"value":7.4,"ontology_term_id":"OCA_TEST:0000004","ontology_term_label":"pH value"},"unit_operation":{"value":"chromatography","ontology_term_id":"OCA_TEST:0000002","ontology_term_label":"chromatography"}}'
            ),
            provider=config.provider or "",
            model=config.model or "",
            latency_ms=5,
            input_chars=len(prompt),
        ),
    )

    result = run_llm_connection_test(
        LlmRuntimeConfig(provider="gemini", api_key="secret", model="gemini-2.5-flash")
    )

    assert result.ok is True
    assert result.provider_key == "gemini"
    assert result.api_key_source == "stored"
    assert result.parsed_json["sample_count"]["value"] == 42
    assert result.parsed_json["sample_count"]["ontology_term_id"] == "OCA_TEST:0000003"
    assert result.content_check_passed is True
    assert result.ontology_mapping_check_passed is True


def test_llm_connection_reports_mocked_provider_error(monkeypatch):
    def fail(prompt, system_prompt, config, json_mode=False):
        raise LlmClientError("LLM provider rejected the API key or permissions.")

    monkeypatch.setattr(clients, "generate_text", fail)

    result = run_llm_connection_test(
        LlmRuntimeConfig(provider="gemini", api_key="secret", model="gemini-2.5-flash")
    )

    assert result.ok is False
    assert result.status == "error"
    assert "rejected" in result.error


def test_gemini_client_construction_uses_default_model():
    client = create_llm_client(LlmRuntimeConfig(provider="gemini", api_key="secret"))

    assert isinstance(client, GeminiLLMClient)
    assert client.model == "gemini-2.5-flash"


def test_gemini_client_accepts_label_alias_and_uses_default_model():
    client = create_llm_client(LlmRuntimeConfig(provider="Gemini API", api_key="secret"))

    assert isinstance(client, GeminiLLMClient)
    assert client.model == "gemini-2.5-flash"


def test_gemini_alias_connection_test_uses_canonical_key_without_api_key():
    result = run_llm_connection_test(LlmRuntimeConfig(provider="Gemini API"))

    assert result.ok is False
    assert result.status == "missing_api_key"
    assert result.provider == "Gemini API"
    assert result.provider_key == "gemini"
    assert result.model == "gemini-2.5-flash"
    assert "Unsupported LLM provider" not in (result.error or "")


def test_unsupported_provider_value_stays_unsupported_with_clear_error():
    result = run_llm_connection_test(
        LlmRuntimeConfig(provider="Not A Real Provider", api_key="secret", model="test-model")
    )

    assert result.ok is False
    assert result.provider_key == "not_a_real_provider"
    assert result.status == "error"
    assert "Unsupported LLM provider" in (result.error or "")
    assert "not_a_real_provider" in (result.error or "")


def test_custom_openai_compatible_requires_base_url():
    with pytest.raises(LlmClientError, match="base URL"):
        create_llm_client(
            LlmRuntimeConfig(provider="openai-compatible", api_key="secret", model="local-model")
        )


def test_custom_openai_compatible_configuration_accepts_manual_model_and_base_url():
    client = create_llm_client(
        LlmRuntimeConfig(
            provider="openai-compatible",
            api_key="secret",
            model="local-model",
            base_url="http://localhost:11434/v1",
        )
    )

    assert client.model == "local-model"
    assert client.base_url == "http://localhost:11434/v1"


def test_api_key_can_come_from_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-secret")
    config = LlmRuntimeConfig(
        provider="gemini",
        api_key_env_var="GEMINI_API_KEY",
        model="gemini-2.5-flash",
    )

    assert config.resolved_api_key == "env-secret"
    assert config.api_key_source == "environment:GEMINI_API_KEY"


def test_estimate_input_size_returns_characters_and_tokens():
    estimate = estimate_input_size("abcd", system_prompt="efgh")

    assert estimate["characters"] == 8
    assert estimate["approx_tokens"] >= 1




def test_llm_connection_sends_markdown_workflow_prompt(monkeypatch):
    seen = {}

    def fake_generate_text(prompt, system_prompt, config, json_mode=False):
        seen["prompt"] = prompt
        seen["system_prompt"] = system_prompt
        seen["json_mode"] = json_mode
        return clients.LlmTextResult(
            text=(
                '{"answer":"understood","sample_count":{"value":42,"ontology_term_id":"OCA_TEST:0000003","ontology_term_label":"sample count"},"ph":{"value":7.4,"ontology_term_id":"OCA_TEST:0000004","ontology_term_label":"pH value"},"unit_operation":{"value":"chromatography","ontology_term_id":"OCA_TEST:0000002","ontology_term_label":"chromatography"}}'
            ),
            provider=config.provider or "",
            model=config.model or "",
            latency_ms=7,
            input_chars=len(prompt),
        )

    monkeypatch.setattr(clients, "generate_text", fake_generate_text)

    result = run_llm_connection_test(
        LlmRuntimeConfig(provider="gemini", api_key="secret", model="gemini-2.5-flash")
    )

    assert result.ok is True
    assert seen["json_mode"] is True
    assert "# Test Literature Entry" in seen["prompt"]
    assert "The experiment used 42 samples." in seen["prompt"]
    assert "OBO ontology:" in seen["prompt"]
    assert "id: OCA_TEST:0000002" in seen["prompt"]
    assert "Read the Markdown text and the OBO ontology." in seen["prompt"]


def test_llm_connection_fails_when_content_check_does_not_match(monkeypatch):
    monkeypatch.setattr(
        clients,
        "generate_text",
        lambda prompt, system_prompt, config, json_mode=False: clients.LlmTextResult(
            text=(
                '{"answer":"understood","sample_count":{"value":3,"ontology_term_id":"OCA_TEST:0000003","ontology_term_label":"sample count"},"ph":{"value":7.4,"ontology_term_id":"OCA_TEST:0000004","ontology_term_label":"pH value"},"unit_operation":{"value":"filtration","ontology_term_id":"OCA_TEST:0000002","ontology_term_label":"chromatography"}}'
            ),
            provider=config.provider or "",
            model=config.model or "",
            latency_ms=5,
            input_chars=len(prompt),
        ),
    )

    result = run_llm_connection_test(
        LlmRuntimeConfig(provider="gemini", api_key="secret", model="gemini-2.5-flash")
    )

    assert result.ok is False
    assert result.status == "validation_failed"
    assert result.content_check_passed is False
    assert "content: sample_count.value must be 42" in result.validation_errors
    assert 'content: unit_operation.value must be "chromatography"' in result.validation_errors
    assert result.ontology_mapping_check_passed is True


def test_llm_connection_fails_when_ontology_mapping_does_not_match(monkeypatch):
    monkeypatch.setattr(
        clients,
        "generate_text",
        lambda prompt, system_prompt, config, json_mode=False: clients.LlmTextResult(
            text=(
                '{"answer":"understood","sample_count":{"value":42,"ontology_term_id":"OCA_TEST:9999999","ontology_term_label":"wrong"},"ph":{"value":7.4,"ontology_term_id":"OCA_TEST:0000004","ontology_term_label":"pH value"},"unit_operation":{"value":"chromatography","ontology_term_id":"OCA_TEST:0000002","ontology_term_label":"chromatography"}}'
            ),
            provider=config.provider or "",
            model=config.model or "",
            latency_ms=5,
            input_chars=len(prompt),
        ),
    )

    result = run_llm_connection_test(
        LlmRuntimeConfig(provider="gemini", api_key="secret", model="gemini-2.5-flash")
    )

    assert result.ok is False
    assert result.status == "validation_failed"
    assert result.content_check_passed is True
    assert result.ontology_mapping_check_passed is False
    assert "ontology: sample_count.ontology_term_id must be OCA_TEST:0000003" in result.validation_errors

