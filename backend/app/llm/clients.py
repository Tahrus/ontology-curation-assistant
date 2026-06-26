from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from backend.app.llm.presets import (
    provider_catalog as _provider_catalog,
    provider_preset,
    normalize_provider_id,
)
from backend.app.services.runtime_config import LlmRuntimeConfig


class LlmClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlmTextResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    input_chars: int
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class LlmConnectionTestResult:
    ok: bool
    provider: str | None
    model: str | None
    api_key_found: bool
    provider_key: str | None = None
    api_key_source: str | None = None
    latency_ms: int | None = None
    response_preview: str | None = None
    status: str = "not_configured"
    error: str | None = None


class LlmClient(Protocol):
    provider: str

    def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> LlmTextResult:
        ...


def estimate_input_size(prompt: str, *, system_prompt: str | None = None) -> dict[str, int]:
    chars = len(prompt) + len(system_prompt or "")
    return {"characters": chars, "approx_tokens": max(1, chars // 4)}


def provider_catalog() -> dict[str, Any]:
    return _provider_catalog()


def generate_text(
    prompt: str,
    *,
    system_prompt: str | None = None,
    config: LlmRuntimeConfig,
) -> LlmTextResult:
    return create_llm_client(config).generate_text(prompt, system_prompt=system_prompt)


def test_llm_connection(config: LlmRuntimeConfig) -> LlmConnectionTestResult:
    provider_key = normalize_provider_id(config.provider)
    if not config.provider:
        return LlmConnectionTestResult(
            ok=False,
            provider=None,
            provider_key=None,
            model=config.model,
            api_key_found=bool(config.resolved_api_key),
            api_key_source=config.api_key_source,
            error="No LLM provider is configured.",
        )
    if not config.resolved_api_key:
        return LlmConnectionTestResult(
            ok=False,
            provider=config.provider,
            provider_key=provider_key,
            model=_model_for(config),
            api_key_found=False,
            api_key_source=config.api_key_source,
            error="No API key was found. Enter a key or set the configured environment variable.",
            status="missing_api_key",
        )
    try:
        result = generate_text(
            "Reply with the single word ok.",
            system_prompt="This is a low-token connectivity test.",
            config=config,
        )
    except LlmClientError as exc:
        return LlmConnectionTestResult(
            ok=False,
            provider=config.provider,
            provider_key=provider_key,
            model=_model_for(config),
            api_key_found=True,
            api_key_source=config.api_key_source,
            status="error",
            error=str(exc),
        )
    return LlmConnectionTestResult(
        ok=True,
        provider=result.provider,
        provider_key=provider_key or result.provider,
        model=result.model,
        api_key_found=True,
        api_key_source=config.api_key_source,
        latency_ms=result.latency_ms,
        response_preview=result.text[:300],
        status="ok",
    )


def create_llm_client(config: LlmRuntimeConfig) -> LlmClient:
    provider = normalize_provider_id(config.provider) or ""
    api_key = config.resolved_api_key
    if not provider:
        raise LlmClientError("No LLM provider is configured.")
    if not api_key:
        raise LlmClientError("No API key was found for the configured LLM provider.")
    if provider == "gemini":
        return GeminiLLMClient(config, api_key)
    if provider == "openai":
        return OpenAILLMClient(config, api_key)
    if provider == "anthropic":
        return AnthropicLLMClient(config, api_key)
    if provider == "openai-compatible":
        return CustomOpenAICompatibleClient(config, api_key)
    raise LlmClientError(f"Unsupported LLM provider: {config.provider} (normalized to {provider}).")


class OpenAILLMClient:
    provider = "openai"

    def __init__(self, config: LlmRuntimeConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        preset = provider_preset("openai")
        self.model = config.model or (preset.default_model if preset else "gpt-4.1-mini")
        self.base_url = (config.base_url or (preset.default_base_url if preset else None) or "https://api.openai.com/v1").rstrip("/")

    def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> LlmTextResult:
        return _call_openai_chat(self.config, self.api_key, self.model, self.base_url, prompt, system_prompt, self.provider)


class CustomOpenAICompatibleClient(OpenAILLMClient):
    provider = "openai-compatible"

    def __init__(self, config: LlmRuntimeConfig, api_key: str):
        if not config.base_url:
            raise LlmClientError("A base URL is required for a custom OpenAI-compatible provider.")
        if not config.model:
            raise LlmClientError("A model name is required for a custom OpenAI-compatible provider.")
        super().__init__(config, api_key)


class GeminiLLMClient:
    provider = "gemini"

    def __init__(self, config: LlmRuntimeConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        preset = provider_preset("gemini")
        self.model = config.model or (preset.default_model if preset else "gemini-2.5-flash")

    def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> LlmTextResult:
        started = time.perf_counter()
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LlmClientError(
                "The google-genai package is required for Gemini support. Install it with `pip install google-genai`."
            ) from exc
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_output_tokens,
                ),
            )
        except Exception as exc:
            raise LlmClientError(_friendly_provider_error(exc)) from exc
        text = getattr(response, "text", None)
        if not text:
            raise LlmClientError("Gemini returned a malformed or empty response.")
        return LlmTextResult(
            text=str(text),
            provider=self.provider,
            model=self.model,
            latency_ms=_elapsed_ms(started),
            input_chars=len(prompt) + len(system_prompt or ""),
        )


class AnthropicLLMClient:
    provider = "anthropic"

    def __init__(self, config: LlmRuntimeConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        preset = provider_preset("anthropic")
        self.model = config.model or (preset.default_model if preset else "claude-3-5-sonnet-latest")
        self.base_url = (config.base_url or (preset.default_base_url if preset else None) or "https://api.anthropic.com/v1").rstrip("/")

    def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> LlmTextResult:
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.config.max_output_tokens,
            "temperature": self.config.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        try:
            response = httpx.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            text = "".join(part.get("text", "") for part in body.get("content", []) if isinstance(part, dict))
        except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
            raise LlmClientError(_friendly_provider_error(exc)) from exc
        if not text:
            raise LlmClientError("Anthropic returned a malformed or empty response.")
        return LlmTextResult(text=text, provider=self.provider, model=self.model, latency_ms=_elapsed_ms(started), input_chars=len(prompt) + len(system_prompt or ""))


def _call_openai_chat(
    config: LlmRuntimeConfig,
    api_key: str,
    model: str,
    base_url: str,
    prompt: str,
    system_prompt: str | None,
    provider: str,
) -> LlmTextResult:
    started = time.perf_counter()
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt or "Return only the requested content."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": config.temperature,
                "max_tokens": config.max_output_tokens,
                "stream": False,
            },
            timeout=config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        text = str(payload["choices"][0]["message"]["content"])
        usage = payload.get("usage") if isinstance(payload, dict) else None
    except (httpx.TimeoutException, httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmClientError(_friendly_provider_error(exc)) from exc
    if not text:
        raise LlmClientError("OpenAI-compatible provider returned an empty response.")
    return LlmTextResult(
        text=text,
        provider=provider,
        model=model,
        latency_ms=_elapsed_ms(started),
        input_chars=len(prompt) + len(system_prompt or ""),
        usage=usage if isinstance(usage, dict) else None,
    )


def _model_for(config: LlmRuntimeConfig) -> str | None:
    if not config.provider:
        return config.model
    preset = provider_preset(config.provider)
    return config.model or (preset.default_model if preset else None)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _friendly_provider_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "LLM request timed out."
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "LLM provider rejected the API key or permissions."
        if status == 404:
            return "LLM provider or model endpoint was not found."
        if status == 429:
            return "LLM provider quota or rate limit was exceeded."
        return f"LLM provider returned HTTP {status}."
    if isinstance(exc, httpx.RequestError):
        return f"Network error while contacting LLM provider: {exc}"
    message = str(exc)
    normalized = message.casefold()
    if any(term in normalized for term in ["api key", "apikey", "unauthenticated", "permission", "auth"]):
        return "LLM provider rejected the API key or permissions."
    if any(term in normalized for term in ["quota", "rate limit", "resource_exhausted", "429"]):
        return "LLM provider quota or rate limit was exceeded."
    if any(term in normalized for term in ["deadline", "timeout", "timed out"]):
        return "LLM request timed out."
    if any(term in normalized for term in ["model", "not found", "404", "unsupported"]):
        return "LLM provider or model endpoint was not found."
    if any(term in normalized for term in ["network", "connect", "dns", "base url", "base_url"]):
        return f"Network error while contacting LLM provider: {message}"
    return message
