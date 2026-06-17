from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass(frozen=True)
class LlmProviderPreset:
    id: str
    label: str
    provider: str
    default_model: str
    models: list[str]
    api_key_env_vars: list[str]
    default_base_url: str | None = None
    default_timeout_seconds: float = 30.0
    default_retry_count: int = 1
    default_temperature: float = 0.0
    default_max_output_tokens: int = 1024
    requires_base_url: bool = False
    manual_model: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROVIDER_PRESETS: dict[str, LlmProviderPreset] = {
    "gemini": LlmProviderPreset(
        id="gemini",
        label="Google Gemini",
        provider="gemini",
        default_model="gemini-2.5-flash",
        models=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-pro", "gemini-1.5-flash"],
        api_key_env_vars=["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    ),
    "openai": LlmProviderPreset(
        id="openai",
        label="OpenAI",
        provider="openai",
        default_model="gpt-4.1-mini",
        models=["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini"],
        api_key_env_vars=["OPENAI_API_KEY"],
        default_base_url="https://api.openai.com/v1",
    ),
    "anthropic": LlmProviderPreset(
        id="anthropic",
        label="Anthropic",
        provider="anthropic",
        default_model="claude-3-5-sonnet-latest",
        models=["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
        api_key_env_vars=["ANTHROPIC_API_KEY"],
        default_base_url="https://api.anthropic.com/v1",
    ),
    "openai-compatible": LlmProviderPreset(
        id="openai-compatible",
        label="Custom / OpenAI-compatible",
        provider="openai-compatible",
        default_model="",
        models=[],
        api_key_env_vars=[],
        requires_base_url=True,
        manual_model=True,
    ),
}


PROVIDER_ALIASES = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "custom": "openai-compatible",
    "custom_openai": "openai-compatible",
    "custom_openai_compatible": "openai-compatible",
    "gemini": "gemini",
    "gemini_api": "gemini",
    "google": "gemini",
    "google_ai": "gemini",
    "google_gemini": "gemini",
    "google_gemini_api": "gemini",
    "google_generative_ai": "gemini",
    "local": "openai-compatible",
    "openai": "openai",
    "openai_compatible": "openai-compatible",
    "chatgpt": "openai",
}


def normalize_llm_provider(provider: str | None) -> str:
    value = (provider or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "openai": "openai",
        "chatgpt": "openai",
        "gemini": "gemini",
        "google": "gemini",
        "google_gemini": "gemini",
        "gemini_api": "gemini",
        "google_ai": "gemini",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "openai_compatible": "openai-compatible",
        "custom_openai_compatible": "openai-compatible",
        "custom": "openai-compatible",
        "local": "openai-compatible",
    }
    # Handle cleanups for other punctuation if present
    normalized_val = aliases.get(value, value)
    if normalized_val == value:
        # Fallback to alphanumeric cleaning for complex names like "Custom / OpenAI-compatible"
        cleaned = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
        return aliases.get(cleaned, cleaned)
    return normalized_val


def normalize_provider_id(provider: str | None) -> str | None:
    if not provider:
        return None
    return normalize_llm_provider(provider)


def provider_preset(provider: str | None) -> LlmProviderPreset | None:
    normalized = normalize_provider_id(provider)
    return PROVIDER_PRESETS.get(normalized or "")


def provider_catalog() -> dict[str, Any]:
    return {"providers": [preset.to_dict() for preset in PROVIDER_PRESETS.values()]}
