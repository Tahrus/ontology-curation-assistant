# AGENTS.md

## Project rules

Before making changes:
- Read `README.md`.
- Read `docs/current-state.md`.
- Read `docs/code-overview.md`.
- Inspect the relevant source files before editing.

After making code changes:
- Update `README.md` if behavior, setup, usage, CLI commands, environment variables, dependencies, or architecture changed.
- Update `docs/current-state.md` with the current implementation status, known limitations, and next logical tasks.
- Update `docs/code-overview.md` if files, modules, APIs, data flow, or architecture changed.
- Add or update tests when behavior changes.
- Run the relevant test/lint/typecheck commands when available.
- Summarize changed files and verification steps in the final response.

Documentation discipline:
- Do not leave documentation stale.
- If a requested change does not require documentation updates, explicitly say why.
- Prefer small, accurate documentation updates over broad rewrites.

Coding style:
- Follow existing project conventions.
- Do not introduce new dependencies unless necessary.
- Keep changes minimal and localized unless a broader refactor is explicitly requested.