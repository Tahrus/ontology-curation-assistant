from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.app.llm.clients import LlmTextResult, generate_text
from backend.app.llm.presets import normalize_provider_id
from backend.app.services.runtime_config import LlmRuntimeConfig


SYSTEM_PROMPT = "Return strict JSON only. Do not create ontology IDs or ontology files."
LOG_DIR = Path("data") / "ontology_suggestions" / "logs" / "api_function_tests"


@dataclass(frozen=True)
class ApiFunctionTestDiagnostics:
    status: str
    stage: str
    provider: str | None
    model: str | None
    base_url: str | None
    api_key_present: bool
    api_key_preview: str
    http_status: int | None = None
    content_type: str | None = None
    response_body_length: int = 0
    raw_response_preview: str | None = None
    parsed_json: bool = False
    schema_valid: bool = False
    json_extraction_method: str = "failed"
    json_recovered: bool = False
    json_recovery_warning: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    suggested_fix: str | None = None
    run_id: str | None = None
    output_path: str | None = None


def diagnostic_payload(result: ApiFunctionTestDiagnostics) -> dict[str, Any]:
    return asdict(result)


def api_key_preview(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) >= 8 and value.startswith(("sk-", "sk_")):
        return f"{value[:3]}...{value[-4:]}"
    return "present_not_displayed"


def validate_minimal_test_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Function test response must be a JSON object.")
    if payload.get("status") != "ok":
        raise ValueError("Function test response field status must be 'ok'.")
    if payload.get("task") != "ontology_suggestion_test":
        raise ValueError("Function test response field task must be 'ontology_suggestion_test'.")
    if not isinstance(payload.get("suggestions"), list):
        raise ValueError("Function test response field suggestions must be a list.")


def run_api_function_test(
    *,
    config: LlmRuntimeConfig,
    prompt_template_id: str,
    task_type: str,
    caller: Any | None = None,
    show_response_preview: bool = True,
    debug: bool = False,
) -> ApiFunctionTestDiagnostics:
    provider = normalize_provider_id(config.provider)
    base_url = config.base_url or _default_base_url(provider)
    model = config.model
    api_key = config.resolved_api_key
    if not provider:
        result = _diagnostic_error("configuration", provider, model, base_url, api_key, "missing_provider", "No LLM provider is configured.", "Select and save an LLM provider before running the function test.")
        return _write_log(result, show_response_preview=show_response_preview, debug=debug)
    if not api_key:
        result = _diagnostic_error("configuration", provider, model, base_url, api_key, "missing_api_key", "No API key was found for the configured provider.", "Enter an API key or configure the expected environment variable.")
        return _write_log(result, show_response_preview=show_response_preview, debug=debug)

    prompt = _test_prompt(prompt_template_id, task_type)
    try:
        raw = caller(prompt, config) if caller else _call_provider(prompt, config, provider, model, base_url, api_key)
    except httpx.TimeoutException as exc:
        result = _diagnostic_error("request", provider, model, base_url, api_key, "timeout", str(exc) or "The request timed out.", "Check network access, endpoint URL, and provider availability; retry with a longer timeout if needed.")
        return _write_log(result, show_response_preview=show_response_preview, debug=debug)
    except httpx.ConnectError as exc:
        result = _diagnostic_error("request", provider, model, base_url, api_key, "connection_error", str(exc), "Check the base URL, network connection, proxy, and DNS configuration.")
        return _write_log(result, show_response_preview=show_response_preview, debug=debug)
    except httpx.RequestError as exc:
        result = _diagnostic_error("request", provider, model, base_url, api_key, "request_error", str(exc), "Check the endpoint URL and local network configuration.")
        return _write_log(result, show_response_preview=show_response_preview, debug=debug)

    if isinstance(raw, httpx.Response):
        result = diagnostics_from_http_response(raw, provider=provider, model=model, base_url=base_url, api_key=api_key)
    elif isinstance(raw, LlmTextResult):
        result = diagnostics_from_response_text(raw.text, provider=raw.provider, model=raw.model, base_url=base_url, api_key=api_key, http_status=None, content_type=None)
    else:
        result = diagnostics_from_response_text(str(raw or ""), provider=provider, model=model, base_url=base_url, api_key=api_key, http_status=None, content_type=None)
    return _write_log(result, show_response_preview=show_response_preview, debug=debug)


def diagnostics_from_http_response(response: httpx.Response, *, provider: str | None, model: str | None, base_url: str | None, api_key: str | None) -> ApiFunctionTestDiagnostics:
    text = response.text or ""
    content_type = response.headers.get("content-type")
    if not 200 <= response.status_code < 300:
        return ApiFunctionTestDiagnostics(
            status="error",
            stage="http_response",
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_present=bool(api_key),
            api_key_preview=api_key_preview(api_key),
            http_status=response.status_code,
            content_type=content_type,
            response_body_length=len(text),
            raw_response_preview=_preview(text),
            error_type="http_error",
            error_message=f"LLM provider returned HTTP {response.status_code}.",
            suggested_fix=_http_suggested_fix(response.status_code),
        )
    return diagnostics_from_response_text(text, provider=provider, model=model, base_url=base_url, api_key=api_key, http_status=response.status_code, content_type=content_type)


def diagnostics_from_response_text(text: str | None, *, provider: str | None, model: str | None, base_url: str | None, api_key: str | None, http_status: int | None, content_type: str | None) -> ApiFunctionTestDiagnostics:
    body = text or ""
    base = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_present": bool(api_key),
        "api_key_preview": api_key_preview(api_key),
        "http_status": http_status,
        "content_type": content_type,
        "response_body_length": len(body),
        "raw_response_preview": _preview(body),
    }
    if not body.strip():
        return ApiFunctionTestDiagnostics(status="error", stage="json_parse", parsed_json=False, schema_valid=False, error_type="empty_response_body", error_message="The API returned an empty response body. JSON parsing was not attempted.", suggested_fix="Check the endpoint URL, model name, authentication, and whether the provider returns a streaming response or a different response format.", **base)
    json_text, method, warning = _extract_json_text(body)
    recovered = method in {"fenced_json", "fenced_code_block", "recovered_substring"}
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return ApiFunctionTestDiagnostics(status="error", stage="json_parse", parsed_json=False, schema_valid=False, json_extraction_method=method, json_recovered=recovered, json_recovery_warning=warning, error_type="invalid_json_response", error_message=f"JSON parser error: {exc}", suggested_fix="The API did not return valid JSON. Check whether the model was instructed to return JSON only, whether the endpoint is correct, and whether the provider returned an HTML/text error page.", **base)
    if isinstance(payload, dict) and "error" in payload:
        return ApiFunctionTestDiagnostics(status="error", stage="schema_validation", parsed_json=True, schema_valid=False, json_extraction_method=method, json_recovered=recovered, json_recovery_warning=warning, error_type="api_error_object", error_message=str(payload.get("error")), suggested_fix="The provider returned a JSON error object. Check API key, model name, endpoint URL, quota, and provider dashboard details.", **base)
    try:
        validate_minimal_test_payload(payload)
    except ValueError as exc:
        return ApiFunctionTestDiagnostics(status="error", stage="schema_validation", parsed_json=True, schema_valid=False, json_extraction_method=method, json_recovered=recovered, json_recovery_warning=warning, error_type="schema_validation_error", error_message=str(exc), suggested_fix="The API returned JSON, but not the required function-test schema. Ensure the prompt asks for the minimal ontology_suggestion_test JSON exactly.", **base)
    status = "warning" if recovered else "success"
    return ApiFunctionTestDiagnostics(status=status, stage="schema_validation", parsed_json=True, schema_valid=True, json_extraction_method=method, json_recovered=recovered, json_recovery_warning=warning, **base)


def _call_provider(prompt: str, config: LlmRuntimeConfig, provider: str | None, model: str | None, base_url: str | None, api_key: str) -> httpx.Response | LlmTextResult:
    if provider in {"openai", "openai-compatible"}:
        if not model:
            raise httpx.RequestError("A model is required for OpenAI-compatible function tests.")
        return httpx.post(
            f"{(base_url or 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": min(config.max_output_tokens, 128),
                "stream": False,
                "response_format": {"type": "json_object"},
            },
            timeout=config.timeout_seconds,
        )
    return generate_text(prompt, system_prompt=SYSTEM_PROMPT, config=config)


def _diagnostic_error(stage: str, provider: str | None, model: str | None, base_url: str | None, api_key: str | None, error_type: str, error_message: str, suggested_fix: str) -> ApiFunctionTestDiagnostics:
    return ApiFunctionTestDiagnostics(status="error", stage=stage, provider=provider, model=model, base_url=base_url, api_key_present=bool(api_key), api_key_preview=api_key_preview(api_key), error_type=error_type, error_message=error_message, suggested_fix=suggested_fix)


def _default_base_url(provider: str | None) -> str | None:
    if provider == "openai":
        return "https://api.openai.com/v1"
    if provider == "anthropic":
        return "https://api.anthropic.com/v1"
    return None


def _http_suggested_fix(status: int) -> str:
    if status in {401, 403}:
        return "Check API key and permissions."
    if status == 404:
        return "Check base URL, endpoint path, and model name."
    if status == 429:
        return "Rate limit or quota exceeded. Check provider billing/usage dashboard or reduce request frequency."
    if status >= 500:
        return "Provider/server error. Retry later or check provider status."
    return "Check provider request settings, endpoint URL, model, and response body."


def _test_prompt(prompt_template_id: str, task_type: str) -> str:
    return "\n".join(
        [
            f"Prompt template id: {prompt_template_id}",
            f"Task type: {task_type}",
            "This is a cheap API function test. Do not use real literature or ontology context.",
            "Return only valid JSON:",
            json.dumps({"status": "ok", "task": "ontology_suggestion_test", "suggestions": []}, indent=2),
        ]
    )


def _preview(text: str | None, limit: int = 1000) -> str:
    return (text or "")[:limit]


_FENCED_JSON_RE = re.compile(r"^```json\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
_FENCED_CODE_RE = re.compile(r"^```\s*(.*?)\s*```$", re.DOTALL)


def _extract_json_text(text: str) -> tuple[str, str, str | None]:
    stripped = text.strip()
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        pass
    else:
        return stripped, "direct", None

    match = _FENCED_JSON_RE.fullmatch(stripped)
    if match:
        return match.group(1).strip(), "fenced_json", "Recovered JSON from a Markdown ```json fenced block."

    match = _FENCED_CODE_RE.fullmatch(stripped)
    if match:
        return match.group(1).strip(), "fenced_code_block", "Recovered JSON from a Markdown fenced code block."

    return stripped, "failed", None


def _write_log(result: ApiFunctionTestDiagnostics, *, show_response_preview: bool, debug: bool) -> ApiFunctionTestDiagnostics:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_id = result.run_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    path = LOG_DIR / f"{run_id}.json"
    payload = diagnostic_payload(result)
    payload["run_id"] = run_id
    payload["output_path"] = str(path)
    if not debug and payload.get("raw_response_preview"):
        payload["raw_response_preview"] = payload["raw_response_preview"][:1000]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    response_payload = {**payload}
    if not show_response_preview:
        response_payload["raw_response_preview"] = None
    return ApiFunctionTestDiagnostics(**response_payload)
