# Active Code Paths

This document identifies the files and functions used by the running Ontology Curation Assistant browser/backend path. It is based on direct source inspection, not Git history.

## Backend Entry And Route Registration

- Backend entry point: `backend/app/main.py`
- FastAPI application object: `app = FastAPI(...)`
- Startup schema initialization: `lifespan()` calls `ensure_runtime_schema()`
- JSON API registration: `app.include_router(router)` imports `router` from `backend.app.api.routes`
- Static browser files: `app.mount("/static", StaticFiles(directory=static_dir), name="static")`
- Browser page serving: `browser_app()` for `/` and `browser_page(page_name)` for `/config`, `/projects`, `/zotero`, `/literature`, `/ontology`, `/curation-prompt`, `/curation`, `/suggestions`, `/evaluation`, and `/export`

## LLM Settings And Connection Test

- LLM settings route: `save_llm_config()` in `backend/app/api/routes.py`, route `POST /api/config/llm`
- Provider catalog route: `llm_provider_catalog()` in `backend/app/api/routes.py`, route `GET /api/config/llm/providers`
- LLM connection-test endpoint: `test_configured_llm()` in `backend/app/api/routes.py`, route `POST /api/config/llm/test`
- Active runtime config loader: `llm_config()` in `backend/app/services/runtime_config.py`
- Runtime config object: `LlmRuntimeConfig` in `backend/app/services/runtime_config.py`
- API key lookup: `LlmRuntimeConfig.resolved_api_key`; stored `llm_api_key` wins, otherwise configured `llm_api_key_env_var` is read from the process environment
- API key source diagnostics: `LlmRuntimeConfig.api_key_source`

The connection-test route calls:

```text
test_configured_llm()
  -> llm_config(session)
  -> test_llm_connection(config)
  -> generate_text(..., config=config)
  -> create_llm_client(config)
```

The response includes `provider`, canonical `provider_key`, `model`, `api_key_found`, `api_key_source`, `latency_ms`, `status`, `response_preview`, and `error`.

## Provider Presets And Dispatch

- Provider presets and default models: `PROVIDER_PRESETS` in `backend/app/llm/presets.py`
- Provider normalization: `normalize_llm_provider()` and `normalize_provider_id()` in `backend/app/llm/presets.py`
- Provider-independent call helper: `generate_text()` in `backend/app/llm/clients.py`
- Provider dispatcher: `create_llm_client()` in `backend/app/llm/clients.py`
- Connection-test helper: `test_llm_connection()` in `backend/app/llm/clients.py`
- Provider clients:
  - `GeminiLLMClient`
  - `OpenAILLMClient`
  - `AnthropicLLMClient`
  - `CustomOpenAICompatibleClient`

`create_llm_client()` normalizes the configured provider before dispatching. This is the active protection against display labels such as `Gemini API` reaching the dispatcher.

## Saved LLM Settings

- Runtime settings table model: `AppSetting` in `backend/app/models/db.py`
- Runtime setting reads/writes: `get_runtime_value()` and `set_runtime_values()` in `backend/app/services/runtime_config.py`
- Saved API config helpers: `_saved_configs()`, `_write_saved_configs()`, `_upsert_saved_config()`, `_public_saved_config()`, and `_active_config_id()` in `backend/app/api/routes.py`
- Saved config list route: `list_saved_api_configs()`, route `GET /api/config/saved`
- Saved config create route: `create_saved_api_config()`, route `POST /api/config/saved`
- Saved config activate route: `activate_saved_api_config()`, route `POST /api/config/saved/{config_id}/activate`

LLM provider values are normalized when saving through `POST /api/config/llm`, when manually creating a saved LLM config through `POST /api/config/saved`, and when activating a saved LLM config.

## Frontend LLM Configuration Path

- Active browser markup: `backend/app/static/index.html`
- LLM provider dropdown: `<select name="provider" id="llm-provider-select">`
- Model dropdown: `<select name="model_select" id="llm-model-select">`
- LLM save button: `Save LLM Config`
- LLM test button: `<button id="test-llm" type="button">Test LLM connection</button>`
- Active browser script: `backend/app/static/app.js`
- Provider loading: `loadLlmProviders()` calls `GET /api/config/llm/providers`
- LLM save handler: `#llm-config-form` submit listener posts to `POST /api/config/llm`
- LLM test handler: `#test-llm` click listener posts to `POST /api/config/llm/test`

The visible UI provider dropdown uses provider preset IDs as option values and provider labels as text:

```javascript
`<option value="${safeText(provider.id)}">${safeText(provider.label)}</option>`
```

The LLM save request body built by the active UI contains:

```json
{
  "provider": "selected provider id",
  "api_key": "optional direct key or null",
  "api_key_env_var": "optional env var or null",
  "model": "manual model override, selected model, or null",
  "base_url": "optional base URL or null",
  "temperature": 0,
  "max_output_tokens": 1024,
  "timeout_seconds": 30,
  "retry_count": 1,
  "stream": false
}
```

The LLM test request body is currently `{}`; the backend uses the saved runtime settings.

## Candidate-Generation LLM Path

- Candidate extraction route: `extract_candidates()` in `backend/app/api/routes.py`, route `POST /api/extraction/candidates`
- Extraction service: `extract_candidates_with_optional_llm()` in `backend/app/llm/service.py`
- Prompt builder: `build_candidate_extraction_prompt()` in `backend/app/extraction/prompts.py`
- LLM call: `generate_text()` in `backend/app/llm/clients.py`
- Dispatcher: `create_llm_client()` in `backend/app/llm/clients.py`

Actual LLM-backed candidate generation uses the same runtime config and provider dispatcher as the connection test, so provider aliases are normalized before real candidate-generation requests.

## Active Ontology Graph Path

- Active graph page markup: `backend/app/static/index.html`
- Active graph script: `backend/app/static/app.js`
- Active graph styles: `backend/app/static/styles.css`
- Ontology page container: `#ontology-tree`
- Ontology details panel: `#ontology-graph-details`
- Curation-page shared graph container: `#curation-ontology-tree`
- Curation-page shared details panel: `#curation-ontology-details`
- Active backend endpoint: `ontology_tree()` in `backend/app/api/routes.py`, route `GET /api/ontology/tree`
- Tree payload builder: `ontology_tree_payload()` in `backend/app/ontology/local.py`

The active browser graph is the top-down ontology tree, not the legacy circular graph. `renderOntologyTree()` in `backend/app/static/app.js` calls `GET /api/ontology/tree?depth_limit=12`, stores the result in `state.ontologyTree`, derives a smaller visible section with `deriveVisibleOntologyTree()`, computes positions with `layoutOntologyTree()`, and renders nodes/edges with `renderOntologyTreeSvg()`.

The active endpoint returns live data from the selected project ontology when a project ontology is available, otherwise it uses the configured/selected local ontology file. The payload includes:

- `nodes`: class records with `id`, `label`, `definition`, `synonyms`, `parent_ids`, `child_ids`, `relations`, `source_ontology`, and `source_file`
- `hierarchy_edges`: `is_a`/subclass edges with `edgeType: "hierarchy"`
- `relation_edges`: lateral semantic relation edges with `edgeType: "semantic"`
- `root_ids`, `roots`, `term_count`, `root_count`, `depth_limit`, and `metadata.source_files`

Ontology nodes are rendered in `renderOntologyTreeSvg()` as SVG groups with class `ontology-tree-node`. Node click handling is attached in that same function. A click sets `state.selectedOntologyNodeId`, rerenders the graph so the selected node receives `is-selected`, dims unrelated visible nodes with `is-dimmed`, updates the details panel through `showOntologyNodeDetails()`, and updates curation status text when the shared curation graph is visible.

The local context behavior is implemented by `selectedOntologyContextIds()` and focus mode in `deriveVisibleOntologyTree()`. `Focus on selected class` sets `state.ontologyFocusNodeId`, enables lateral relation display on the Ontology page, and shows the selected node with its parent path, direct descendants within the depth limit, and direct semantic relation endpoints when present. `Reset overview` clears focus, selection, collapsed nodes, search/root filters, and viewport transform.

The older `GET /api/ontology/graph` route and dashboard meta-ontology graph still exist for compatibility/status visualization, but they are not the active class-hierarchy graph page.

## CLI LLM Test Path

- CLI entry point: `backend/app/cli.py`
- Typer app command: `llm_test()`, command `oca llm-test`
- Runtime config: `llm_config(session)`
- Test helper: `test_llm_connection(config)`

The CLI prints provider, provider key, model, key presence/source, status, latency, response preview, and error text.

## Compatibility Or Non-Primary Paths

- `backend/app/llm/service.py` contains `_call_openai_compatible()`, a compatibility helper that manually constructs an OpenAI-compatible `LlmRuntimeConfig`; it is not the browser LLM connection-test path.
- `backend/app/ontology/graph` and the dashboard meta-ontology graph remain available, but they are unrelated to the LLM provider connection test.
- The standalone `zotero_lit_md/` package is a separate PDF/Markdown CLI package and is not part of the browser LLM connection-test path.
