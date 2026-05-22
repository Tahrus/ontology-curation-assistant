# Implementation Roadmap

## Phase 1: Working Skeleton

- Keep current FastAPI and CLI scaffold.
- Add SQLAlchemy models and Alembic migrations.
- Add document ingestion for plain text and PDFs.
- Add a local SQLite development mode.

Acceptance: a document can be registered and parsed into text segments.

## Phase 2: AI Extraction

- Add provider-neutral LLM client.
- Validate model output against JSON schemas.
- Store prompt versions, raw outputs, and parsed candidates.
- Add deterministic mocked extraction tests.

Acceptance: candidates are created with evidence and extraction metadata.

## Phase 3: Review UI

- Add candidate dashboard.
- Add evidence side-by-side view.
- Add approve, edit, reject, duplicate, and needs-more-evidence actions.
- Add audit logging.

Acceptance: reviewer decisions change export eligibility.

## Phase 4: ODK Export

- Generate ROBOT template TSV files for approved candidates.
- Generate SSSOM TSV files for approved mappings.
- Preview files before writing.
- Run configured ODK/Make validation commands.

Acceptance: approved rows can pass through an ODK-managed ontology build.

## Phase 5: Production Workflow

- Add Git branch creation and commits.
- Add pull request creation.
- Add authentication and reviewer roles.
- Add batch reports and quality metrics.

Acceptance: ontology curators can review a batch, export it, validate it, and submit it through Git review.

