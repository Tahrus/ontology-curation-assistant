# LLM Providers

The app uses a provider-neutral LLM layer. Browser configuration, CLI diagnostics, candidate extraction, and ontology suggestion workflows should all go through the same runtime config and client abstraction.

## Files

- Presets and provider aliases: `backend/app/llm/presets.py`
- Client interface and provider clients: `backend/app/llm/clients.py`
- Runtime config and secret resolution: `backend/app/services/runtime_config.py`
- Browser API routes: `backend/app/api/routes.py`
- CLI diagnostics: `backend/app/cli.py`
- Tests: `backend/tests/test_llm_clients.py`, `backend/tests/test_browser_api.py`

## Supported Providers

- Gemini: canonical provider key `gemini`; default model `gemini-2.5-flash`; key env vars `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- OpenAI: canonical provider key `openai`; default model `gpt-4.1-mini`; key env var `OPENAI_API_KEY`
- Anthropic: canonical provider key `anthropic`; default model `claude-3-5-sonnet-latest`; key env var `ANTHROPIC_API_KEY`
- Custom OpenAI-compatible endpoint: canonical provider key `openai-compatible`; requires model and base URL

Provider input is normalized before saving config, activating saved configs, creating clients, or running real candidate-generation LLM requests. Accepted aliases include:

- Gemini: `Gemini API`, `Gemini`, `gemini`, `Google Gemini`, `google`, `google_gemini`, `google-ai`, `google_ai`
- OpenAI: `OpenAI`, `openai`, `ChatGPT`
- Anthropic: `Anthropic`, `anthropic`, `Claude`
- Custom OpenAI-compatible: `openai-compatible`, `openai_compatible`, `Custom / OpenAI-compatible`, `custom`, `local`

The LLM test response includes both `provider` and `provider_key` so diagnostics can show the saved value and the canonical key used by the backend.

## Active Path

The browser `Test LLM connection` button in `backend/app/static/index.html` is wired in `backend/app/static/app.js` and posts `{}` to `POST /api/config/llm/test`. The route `test_configured_llm()` in `backend/app/api/routes.py` loads `llm_config(session)` and calls `test_llm_connection()` in `backend/app/llm/clients.py`. Real candidate extraction through `POST /api/extraction/candidates` also calls `generate_text()` and `create_llm_client()`, so it uses the same provider normalization.

## Diagnostics

`POST /api/config/llm/test` and `oca llm-test` send a tiny prompt through the selected provider. The result reports provider, provider key, model, API key presence/source, latency, status, short response preview, and an actionable error. API keys must not be returned.

Expected error classes include missing API key, invalid key or permissions, quota/rate limit, timeout, network/base URL failure, unsupported model or endpoint, malformed response, and missing provider package.
