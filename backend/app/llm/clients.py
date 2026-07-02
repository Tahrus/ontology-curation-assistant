from __future__ import annotations

import json
import re
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
    raw_response_preview: str | None = None
    parsed_json: dict[str, Any] | None = None
    json_parse_error: str | None = None
    validation_errors: list[str] | None = None
    content_check_passed: bool = False
    ontology_mapping_check_passed: bool = False
    status: str = "not_configured"
    error: str | None = None


class LlmClient(Protocol):
    provider: str

    def generate_text(self, prompt: str, *, system_prompt: str | None = None, json_mode: bool = False) -> LlmTextResult:
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
    json_mode: bool = False,
) -> LlmTextResult:
    return create_llm_client(config).generate_text(prompt, system_prompt=system_prompt, json_mode=json_mode)


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
            _markdown_workflow_test_prompt(),
            system_prompt="Read the supplied Markdown and OBO ontology. Return strict JSON only.",
            config=config,
            json_mode=True,
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
    raw_preview = result.text[:1000]
    parsed, parse_error = _parse_json_response(result.text)
    validation_errors = _validate_markdown_workflow_payload(parsed) if parsed is not None else []
    content_check_passed = parsed is not None and not any(error.startswith("content:") for error in validation_errors)
    ontology_mapping_check_passed = parsed is not None and not any(error.startswith("ontology:") for error in validation_errors)
    checks_passed = content_check_passed and ontology_mapping_check_passed and not validation_errors
    if parse_error:
        status = "invalid_json"
        error = f"LLM response could not be parsed as JSON: {parse_error}"
    elif validation_errors:
        status = "validation_failed"
        error = "LLM JSON response did not match the Markdown content: " + "; ".join(validation_errors)
    else:
        status = "ok"
        error = None
    return LlmConnectionTestResult(
        ok=checks_passed,
        provider=result.provider,
        provider_key=provider_key or result.provider,
        model=result.model,
        api_key_found=True,
        api_key_source=config.api_key_source,
        latency_ms=result.latency_ms,
        response_preview=result.text[:300],
        raw_response_preview=raw_preview,
        parsed_json=parsed,
        json_parse_error=parse_error,
        validation_errors=validation_errors,
        content_check_passed=content_check_passed,
        ontology_mapping_check_passed=ontology_mapping_check_passed,
        status=status,
        error=error,
    )


def _markdown_workflow_test_prompt() -> str:
    markdown = """# Test Literature Entry

Title: Example bioprocess paper

The experiment used 42 samples.
The buffer pH was 7.4.
The main unit operation was chromatography."""
    obo = """format-version: 1.4
ontology: oca-test

[Term]
id: OCA_TEST:0000001
name: bioprocess experiment
def: "An experiment performed to study or operate a bioprocess." []

[Term]
id: OCA_TEST:0000002
name: chromatography
def: "A separation unit operation based on differential interaction with a stationary phase." []
is_a: OCA_TEST:0000001 ! bioprocess experiment

[Term]
id: OCA_TEST:0000003
name: sample count
def: "A data item representing the number of samples used in an experiment." []

[Term]
id: OCA_TEST:0000004
name: pH value
def: "A data item representing the acidity or alkalinity of a solution." []

[Typedef]
id: OCA_TEST:0000101
name: has measurement value
def: "A relation between a measured property and its numeric value." []"""
    expected_shape = {
        "answer": "short confirmation",
        "sample_count": {
            "value": 42,
            "ontology_term_id": "OCA_TEST:0000003",
            "ontology_term_label": "sample count",
        },
        "ph": {
            "value": 7.4,
            "ontology_term_id": "OCA_TEST:0000004",
            "ontology_term_label": "pH value",
        },
        "unit_operation": {
            "value": "chromatography",
            "ontology_term_id": "OCA_TEST:0000002",
            "ontology_term_label": "chromatography",
        },
    }
    return "\n\n".join(
        [
            "Markdown:",
            markdown,
            "OBO ontology:",
            obo,
            "Prompt:",
            "Read the Markdown text and the OBO ontology.",
            "Extract the requested information from the Markdown and map it to the best matching OBO term.",
            "Return JSON only.",
            "Expected JSON shape:",
            json.dumps(expected_shape, indent=2),
        ]
    )

def _parse_json_response(text: str) -> tuple[dict[str, Any] | None, str | None]:
    body = (text or "").strip()
    if not body:
        return None, "empty response"
    candidates = [body]
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    first = body.find("{")
    last = body.rfind("}")
    if first != -1 and last > first:
        candidates.append(body[first : last + 1])
    last_error = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            continue
        if not isinstance(payload, dict):
            return None, "JSON response must be an object"
        return payload, None
    return None, last_error or "invalid JSON"


def _validate_markdown_workflow_payload(payload: dict[str, Any] | None) -> list[str]:
    if payload is None:
        return ["content: no parsed JSON payload was available"]
    errors: list[str] = []

    sample_count = _object_field(payload, "sample_count", errors)
    if sample_count is not None:
        if sample_count.get("value") != 42:
            errors.append("content: sample_count.value must be 42")
        _require_ontology_mapping(sample_count, "sample_count", "OCA_TEST:0000003", "sample count", errors)

    ph = _object_field(payload, "ph", errors)
    if ph is not None:
        try:
            ph_value = float(ph.get("value"))
        except (TypeError, ValueError):
            errors.append("content: ph.value must be numeric value 7.4")
        else:
            if abs(ph_value - 7.4) > 0.001:
                errors.append("content: ph.value must be 7.4")
        _require_ontology_mapping(ph, "ph", "OCA_TEST:0000004", "pH value", errors)

    unit_operation = _object_field(payload, "unit_operation", errors)
    if unit_operation is not None:
        if str(unit_operation.get("value") or "").strip().casefold() != "chromatography":
            errors.append('content: unit_operation.value must be "chromatography"')
        _require_ontology_mapping(unit_operation, "unit_operation", "OCA_TEST:0000002", "chromatography", errors)

    return errors


def _object_field(payload: dict[str, Any], field: str, errors: list[str]) -> dict[str, Any] | None:
    value = payload.get(field)
    if not isinstance(value, dict):
        errors.append(f"content: {field} must be a JSON object")
        return None
    return value


def _require_ontology_mapping(
    value: dict[str, Any],
    field: str,
    expected_id: str,
    expected_label: str,
    errors: list[str],
) -> None:
    if str(value.get("ontology_term_id") or "").strip() != expected_id:
        errors.append(f"ontology: {field}.ontology_term_id must be {expected_id}")
    if str(value.get("ontology_term_label") or "").strip().casefold() != expected_label.casefold():
        errors.append(f'ontology: {field}.ontology_term_label must be "{expected_label}"')

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

    def generate_text(self, prompt: str, *, system_prompt: str | None = None, json_mode: bool = False) -> LlmTextResult:
        return _call_openai_chat(self.config, self.api_key, self.model, self.base_url, prompt, system_prompt, self.provider, json_mode=json_mode)


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

    def generate_text(self, prompt: str, *, system_prompt: str | None = None, json_mode: bool = False) -> LlmTextResult:
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
                    response_mime_type="application/json" if json_mode else None,
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

    def generate_text(self, prompt: str, *, system_prompt: str | None = None, json_mode: bool = False) -> LlmTextResult:
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
    *,
    json_mode: bool = False,
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
                **({"response_format": {"type": "json_object"}} if json_mode else {}),
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






