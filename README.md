# Ontology Curation Assistant

Human-in-the-loop software scaffold for AI-assisted ontology development with ODK-compatible exports.

This project helps ontology developers ingest scientific literature, extract candidate ontology terms and relations, review them with domain experts, and export only approved content into ODK/ROBOT-friendly files.

## Current Status

This is a project scaffold with:

- FastAPI backend structure
- Typer CLI entrypoint
- SQLite/PostgreSQL-ready settings
- JSON schemas for candidate terms and relations
- prompt templates for reproducible extraction
- ODK integration configuration pointing to `C:\Users\ge47vob\ontology-development-kit`
- documentation for architecture, workflow, and ODK integration
- starter tests

AI suggestions are intentionally separated from approved ontology exports.

## Layout

```text
ontology-curation-assistant/
  backend/
    app/
      api/
      audit/
      config.py
      extraction/
      main.py
      models/
      odk/
      ontology/
      review/
      services/
    tests/
  docs/
  examples/
  prompts/
  schemas/
  pyproject.toml
  .env.example
```

## Quick Start

```powershell
cd ontology-curation-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
oca --help
uvicorn backend.app.main:app --reload
```

## ODK Configuration

The default `.env.example` uses:

```text
OCA_ODK_HOME=C:\Users\ge47vob\ontology-development-kit
```

For a real ontology project, set:

```text
OCA_ONTOLOGY_REPO=C:\path\to\your\odk-managed-ontology
```

The assistant should generate reviewed templates into the ontology repository, then run configured ODK or Make targets.

## Safety Rule

The AI layer may create candidates. It may not create ontology changes. Only human-approved records are eligible for ODK export.

