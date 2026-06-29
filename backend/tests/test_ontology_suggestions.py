import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db import session as db_session
from backend.app.models.db import AppSetting, CandidateTermRecord, CurationRun, Project, Suggestion
from backend.app.ontology_suggestion_diagnostics import diagnostics_from_http_response, diagnostics_from_response_text
from backend.app.ontology_suggestions import (
    INITIAL_TEMPLATES,
    Pricing,
    cheap_function_test,
    estimate_cost,
    deactivate_prompt_template,
    duplicate_prompt_template,
    get_prompt_template,
    list_prompt_templates,
    llm_pipeline_test,
    prepare_suggestion_request,
    review_suggestion_to_candidate,
    run_suggestions,
)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database_path = tmp_path / "suggestions.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    db_session.ensure_runtime_schema()
    with factory() as session:
        yield session


@pytest.fixture()
def project(session, tmp_path):
    project = Project(
        name="Protein precipitation",
        slug="protein-precipitation",
        ontology_id="ppo",
        local_path=str(tmp_path / "projects" / "protein-precipitation"),
        editable_ontology_path=str(tmp_path / "ppo.obo"),
        active=True,
    )
    session.add(project)
    session.add(AppSetting(key="llm_provider", value="openai"))
    session.add(AppSetting(key="llm_api_key", value="test-key"))
    session.add(AppSetting(key="llm_model", value="gpt-test"))
    session.commit()
    Path(project.editable_ontology_path).write_text(
        "[Term]\nid: PPO:0000001\nname: protein precipitation\ndef: \"process\" []\n",
        encoding="utf-8",
    )
    return project


def test_prompt_template_loading(tmp_path, monkeypatch):
    import backend.app.ontology_suggestions as service

    monkeypatch.setattr(service, "DATA_ROOT", tmp_path / "data" / "ontology_suggestions")
    monkeypatch.setattr(service, "PROMPT_DIR", service.DATA_ROOT / "prompts")
    monkeypatch.setattr(service, "RUN_DIR", service.DATA_ROOT / "runs")
    monkeypatch.setattr(service, "LOG_DIR", service.DATA_ROOT / "logs")
    monkeypatch.setattr(service, "TEMPLATE_FILE", service.PROMPT_DIR / "templates.json")

    templates = list_prompt_templates()

    assert {item.id for item in templates} >= {item["id"] for item in INITIAL_TEMPLATES}
    assert get_prompt_template("duplicate_check").task_type == "duplicate_check"
    assert get_prompt_template("duplicate_check").title == "Duplicate check"
    assert get_prompt_template("duplicate_check").short_description
    prompt_files = sorted(service.PROMPT_DIR.glob("*.md"))
    assert {path.name for path in prompt_files} >= {f"{item['id']}.md" for item in INITIAL_TEMPLATES}
    text = (service.PROMPT_DIR / "conservative_term_suggestions.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert 'id: "conservative_term_suggestions"' in text
    assert "# Task" in text


def test_prompt_duplicate_and_archive_use_markdown_files(tmp_path, monkeypatch):
    import backend.app.ontology_suggestions as service

    monkeypatch.setattr(service, "DATA_ROOT", tmp_path / "data" / "ontology_suggestions")
    monkeypatch.setattr(service, "PROMPT_DIR", service.DATA_ROOT / "prompts")
    monkeypatch.setattr(service, "RUN_DIR", service.DATA_ROOT / "runs")
    monkeypatch.setattr(service, "LOG_DIR", service.DATA_ROOT / "logs")
    monkeypatch.setattr(service, "TEMPLATE_FILE", service.PROMPT_DIR / "templates.json")

    duplicate = duplicate_prompt_template("duplicate_check", "duplicate_check_copy")
    assert duplicate.id == "duplicate_check_copy"
    assert duplicate.version == 1
    assert (service.PROMPT_DIR / "duplicate_check_copy.md").exists()
    assert not (service.PROMPT_DIR / "duplicate_check_copy.json").exists()

    archived = deactivate_prompt_template("duplicate_check_copy")
    assert archived.active is False
    assert "duplicate_check_copy" not in {item.id for item in list_prompt_templates()}
    assert "duplicate_check_copy" in {item.id for item in list_prompt_templates(include_inactive=True)}
    archived_text = (service.PROMPT_DIR / "duplicate_check_copy.md").read_text(encoding="utf-8")
    assert "active: false" in archived_text


def test_prompt_template_ids_must_be_filesystem_safe(tmp_path, monkeypatch):
    import backend.app.ontology_suggestions as service

    monkeypatch.setattr(service, "DATA_ROOT", tmp_path / "data" / "ontology_suggestions")
    monkeypatch.setattr(service, "PROMPT_DIR", service.DATA_ROOT / "prompts")
    monkeypatch.setattr(service, "RUN_DIR", service.DATA_ROOT / "runs")
    monkeypatch.setattr(service, "LOG_DIR", service.DATA_ROOT / "logs")
    monkeypatch.setattr(service, "TEMPLATE_FILE", service.PROMPT_DIR / "templates.json")

    with pytest.raises(ValueError, match="letters, numbers"):
        duplicate_prompt_template("duplicate_check", "bad/id")


def test_cheap_function_test_uses_dummy_context(session, project, monkeypatch):
    seen = {}

    def caller(prompt, config):
        seen["prompt"] = prompt
        return json.dumps({"status": "ok", "task": "ontology_suggestion_test", "suggestions": []})

    result = cheap_function_test(
        session,
        project_ref=project.slug,
        prompt_template_id="conservative_term_suggestions",
        caller=caller,
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert "ontology_suggestion_test" in seen["prompt"]
    assert session.scalars(select(Suggestion)).all() == []


def test_missing_api_key_blocks_cheap_test(session, project):
    session.query(AppSetting).filter(AppSetting.key == "llm_api_key").delete()
    session.commit()

    result = cheap_function_test(session, project_ref=project.slug, prompt_template_id="duplicate_check")

    assert result["status"] == "error"
    assert result["stage"] == "configuration"
    assert result["error_type"] == "missing_api_key"


def test_pipeline_request_assembly_contains_real_inputs(session, project, monkeypatch):
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "literature_markdown": "# Paper\nAmmonium sulfate precipitates proteins."}],
    )
    monkeypatch.setattr("backend.app.ontology_suggestions.build_ontology_context", lambda project, mode: "PPO:0000001 | protein precipitation | definition: process")

    request = prepare_suggestion_request(
        session,
        project_ref=project.slug,
        prompt_template_id="conservative_term_suggestions",
        literature_scope="one",
        literature_ids=["paper-1"],
        ontology_context_mode="labels_definitions_relations",
    )

    assert "# Literature Markdown" in request["prompt"]
    assert "Ammonium sulfate precipitates proteins" in request["prompt"]
    assert "protein precipitation" in request["prompt"]
    assert "Conservative term suggestions" in request["prompt"]
    assert request["estimated_input_tokens"] > 0


def test_llm_pipeline_test_direct_json_validates(session, project, monkeypatch):
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "literature_markdown": "# Paper\nSalt precipitation evidence."}],
    )
    monkeypatch.setattr("backend.app.ontology_suggestions.build_ontology_context", lambda project, mode: "PPO:0000001 | protein precipitation")
    seen = {}

    def caller(prompt, config):
        seen["prompt"] = prompt
        return json.dumps({
            "status": "ok",
            "task": "llm_pipeline_test",
            "received_inputs": {"literature_markdown": True, "ontology_context": True, "prompt_template": True},
            "detected_context": {"literature_title_or_topic": "salt precipitation", "ontology_terms_seen": ["protein precipitation"], "prompt_task_type": "term_suggestion"},
            "test_suggestion": {"suggestion_type": "none", "label": None, "evidence_quote": None, "confidence": "none"},
            "warnings": [],
        })

    result = llm_pipeline_test(session, project_ref=project.slug, prompt_template_id="conservative_term_suggestions", literature_ids=["paper-1"], caller=caller)

    assert result["ok"] is True
    assert result["schema_valid"] is True
    assert result["json_extraction_method"] == "direct_json"
    assert "Salt precipitation evidence" in seen["prompt"]
    assert session.scalars(select(Suggestion)).all() == []


def test_llm_pipeline_test_fenced_json_recovers_with_warning(session, project, monkeypatch):
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "literature_markdown": "# Paper\nSalt precipitation evidence."}],
    )
    monkeypatch.setattr("backend.app.ontology_suggestions.build_ontology_context", lambda project, mode: "PPO:0000001 | protein precipitation")
    body = """```json
{"status":"ok","task":"llm_pipeline_test","received_inputs":{"literature_markdown":true,"ontology_context":true,"prompt_template":true},"detected_context":{"literature_title_or_topic":"salt","ontology_terms_seen":["protein precipitation"],"prompt_task_type":"term_suggestion"},"test_suggestion":{"suggestion_type":"none","label":null,"evidence_quote":null,"confidence":"none"},"warnings":[]}
```"""

    result = llm_pipeline_test(session, project_ref=project.slug, prompt_template_id="conservative_term_suggestions", literature_ids=["paper-1"], caller=lambda prompt, config: body)

    assert result["status"] == "warning"
    assert result["schema_valid"] is True
    assert result["json_extraction_method"] == "fenced_json"
    assert result["json_recovered"] is True


def test_llm_pipeline_test_malformed_json_diagnostic(session, project, monkeypatch):
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "literature_markdown": "# Paper\nText."}],
    )
    monkeypatch.setattr("backend.app.ontology_suggestions.build_ontology_context", lambda project, mode: "PPO:0000001 | protein precipitation")

    result = llm_pipeline_test(session, project_ref=project.slug, prompt_template_id="conservative_term_suggestions", literature_ids=["paper-1"], caller=lambda prompt, config: "not json")

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_json_response"
    assert result["schema_valid"] is False


def test_prepare_request_missing_markdown_file_is_clear(session, project, tmp_path, monkeypatch):
    missing = tmp_path / "missing.md"
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "markdown_file": str(missing)}],
    )

    with pytest.raises(ValueError, match="Markdown file does not exist"):
        prepare_suggestion_request(session, project_ref=project.slug, prompt_template_id="conservative_term_suggestions", literature_ids=["paper-1"])


def test_prepare_request_missing_ontology_file_is_clear(session, project, monkeypatch):
    Path(project.editable_ontology_path).unlink()
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "literature_markdown": "# Paper"}],
    )

    with pytest.raises(ValueError, match="no readable ontology file"):
        prepare_suggestion_request(session, project_ref=project.slug, prompt_template_id="conservative_term_suggestions", literature_ids=["paper-1"])


def test_malformed_prompt_front_matter_is_clear(tmp_path, monkeypatch):
    import backend.app.ontology_suggestions as service

    monkeypatch.setattr(service, "DATA_ROOT", tmp_path / "data" / "ontology_suggestions")
    monkeypatch.setattr(service, "PROMPT_DIR", service.DATA_ROOT / "prompts")
    monkeypatch.setattr(service, "RUN_DIR", service.DATA_ROOT / "runs")
    monkeypatch.setattr(service, "LOG_DIR", service.DATA_ROOT / "logs")
    monkeypatch.setattr(service, "TEMPLATE_FILE", service.PROMPT_DIR / "templates.json")
    service.PROMPT_DIR.mkdir(parents=True)
    (service.PROMPT_DIR / "bad.md").write_text("---\nid: bad\n---\nBody", encoding="utf-8")

    with pytest.raises(ValueError, match="missing metadata fields"):
        service.list_prompt_templates(include_inactive=True)


def test_malformed_json_response_is_not_persisted(session, project, monkeypatch):
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "literature_markdown": "content"}],
    )
    monkeypatch.setattr("backend.app.ontology_suggestions.build_ontology_context", lambda project, mode: "PPO:1 | term")

    with pytest.raises(ValueError, match="not valid"):
        run_suggestions(
            session,
            project_ref=project.slug,
            prompt_template_id="relation_suggestions",
            literature_scope="one",
            literature_ids=["paper-1"],
            ontology_context_mode="labels_definitions_relations",
            caller=lambda prompt, config: "not json",
        )

    assert session.scalars(select(Suggestion)).all() == []


def test_token_cost_estimation_warns_on_budget():
    result = estimate_cost(
        10_000,
        5_000,
        Pricing(input_cost_per_1m_tokens=10, output_cost_per_1m_tokens=20, monthly_budget=0.25, estimated_spend_this_month=0.1),
    )

    assert result["estimated_cost"] == 0.2
    assert result["budget_warning"] is True


def test_single_paper_suggestion_run_persists_reviewable_suggestion(session, project, monkeypatch):
    monkeypatch.setattr(
        "backend.app.ontology_suggestions.select_literature",
        lambda project, scope, literature_ids: [{"id": "paper-1", "title": "Paper", "literature_markdown": "content"}],
    )
    monkeypatch.setattr("backend.app.ontology_suggestions.build_ontology_context", lambda project, mode: "PPO:1 | term")

    payload = {
        "literature_id": "paper-1",
        "project_id": project.slug,
        "ontology_id": "ppo",
        "prompt_template_id": "conservative_term_suggestions",
        "suggestions": [
            {
                "suggestion_type": "class",
                "label": "salt-induced precipitation",
                "proposed_parent": "protein precipitation",
                "definition": "A precipitation process induced by salt.",
                "relation": None,
                "target": None,
                "evidence_quote": "Salt induced precipitation.",
                "evidence_location": "Results",
                "confidence": "high",
                "rationale": "Directly stated.",
                "requires_human_check": True,
            }
        ],
    }

    result = run_suggestions(
        session,
        project_ref=project.slug,
        prompt_template_id="conservative_term_suggestions",
        literature_scope="one",
        literature_ids=["paper-1"],
        ontology_context_mode="labels_definitions_relations",
        caller=lambda prompt, config: json.dumps(payload),
    )

    assert result["suggestion_count"] == 1
    assert result["preview"]["prompt_template_title"] == "Conservative term suggestions"
    suggestion = session.scalar(select(Suggestion))
    assert suggestion.label == "salt-induced precipitation"
    run = session.get(CurationRun, result["curation_run_id"])
    context = json.loads(run.context_configuration_json)
    assert context["prompt_template_id"] == "conservative_term_suggestions"
    assert context["prompt_template_title"] == "Conservative term suggestions"
    assert context["prompt_template_version"] == 1
    assert "input_assembly" in context


def test_accepting_suggestion_creates_candidate(session, project):
    from backend.app.models.db import CurationRun

    run = CurationRun(
        project_id=project.id,
        name="Run",
        prompt_strategy="ontology_suggestions",
        context_configuration_json="{}",
        prompt_text="Prompt",
    )
    session.add(run)
    session.flush()
    suggestion = Suggestion(
        project_id=project.id,
        curation_run_id=run.id,
        suggestion_type="class",
        label="salt-induced precipitation",
        definition="A precipitation process induced by salt.",
        parent_class="protein precipitation",
        evidence_text="Salt induced precipitation.",
        evidence_json=json.dumps([{"quote": "Salt induced precipitation."}]),
        confidence="high",
        raw_llm_output=json.dumps({"rationale": "Direct evidence."}),
    )
    session.add(suggestion)
    session.commit()

    result = review_suggestion_to_candidate(session, suggestion_id=suggestion.id, status="accepted")

    assert result["candidate_id"]
    candidate = session.scalar(select(CandidateTermRecord))
    assert candidate.label == "salt-induced precipitation"
    assert candidate.review_status == "new"


def test_empty_response_body_diagnostic():
    result = diagnostics_from_response_text("", provider="openai", model="gpt-test", base_url="https://api.example", api_key="sk-test", http_status=200, content_type="application/json")

    assert result.error_type == "empty_response_body"
    assert result.parsed_json is False


def test_html_response_body_diagnostic():
    result = diagnostics_from_response_text("<html>bad</html>", provider="openai", model="gpt-test", base_url="https://api.example", api_key="sk-test", http_status=200, content_type="text/html")

    assert result.error_type == "invalid_json_response"
    assert result.json_extraction_method == "failed"
    assert result.raw_response_preview.startswith("<html>")


def test_gemini_fenced_json_response_is_recovered():
    body = """```json
{
  "status": "ok",
  "task": "ontology_suggestion_test",
  "suggestions": []
}
```"""

    result = diagnostics_from_response_text(body, provider="gemini", model="gemini-2.5-flash", base_url=None, api_key="present", http_status=200, content_type="text/plain")

    assert result.status == "warning"
    assert result.schema_valid is True
    assert result.json_extraction_method == "fenced_json"
    assert result.json_recovered is True
    assert result.raw_response_preview.startswith("```json")


def test_plain_fenced_json_response_is_recovered():
    body = """```
{"status":"ok","task":"ontology_suggestion_test","suggestions":[]}
```"""

    result = diagnostics_from_response_text(body, provider="gemini", model="gemini-2.5-flash", base_url=None, api_key="present", http_status=200, content_type="text/plain")

    assert result.schema_valid is True
    assert result.json_extraction_method == "fenced_code_block"
    assert result.json_recovered is True


def test_malformed_fenced_json_fails_clearly():
    body = """```json
{"status": "ok",
```"""

    result = diagnostics_from_response_text(body, provider="gemini", model="gemini-2.5-flash", base_url=None, api_key="present", http_status=200, content_type="text/plain")

    assert result.status == "error"
    assert result.error_type == "invalid_json_response"
    assert result.json_extraction_method == "fenced_json"
    assert result.json_recovered is True


@pytest.mark.parametrize(("status", "snippet"), [(401, "API key"), (404, "base URL"), (429, "Rate limit")])
def test_http_error_diagnostics(status, snippet):
    response = httpx.Response(status, text="error body", headers={"content-type": "text/plain"})

    result = diagnostics_from_http_response(response, provider="openai", model="gpt-test", base_url="https://api.example", api_key="sk-test")

    assert result.error_type == "http_error"
    assert snippet in result.suggested_fix


def test_valid_json_wrong_schema_diagnostic():
    result = diagnostics_from_response_text(json.dumps({"status": "ok"}), provider="openai", model="gpt-test", base_url="https://api.example", api_key="sk-test", http_status=200, content_type="application/json")

    assert result.error_type == "schema_validation_error"
    assert result.parsed_json is True
    assert result.schema_valid is False


def test_valid_function_test_json_diagnostic():
    result = diagnostics_from_response_text(json.dumps({"status": "ok", "task": "ontology_suggestion_test", "suggestions": []}), provider="openai", model="gpt-test", base_url="https://api.example", api_key="sk-test", http_status=200, content_type="application/json")

    assert result.status == "success"
    assert result.schema_valid is True
    assert result.json_extraction_method == "direct"
    assert result.json_recovered is False
