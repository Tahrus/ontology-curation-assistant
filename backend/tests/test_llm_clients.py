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
        lambda prompt, system_prompt, config: clients.LlmTextResult(
            text="ok",
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
    assert result.response_preview == "ok"


def test_llm_connection_reports_mocked_provider_error(monkeypatch):
    def fail(prompt, system_prompt, config):
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
