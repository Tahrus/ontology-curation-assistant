from pathlib import Path

import typer
from rich.console import Console

from backend.app.config import get_settings
from backend.app.odk.integration import OdkProjectConfig, preview_export_path


app = typer.Typer(help="Ontology Curation Assistant command line tools.")
literature_app = typer.Typer(help="Literature repository commands.")
project_app = typer.Typer(help="Project management commands.")
curation_app = typer.Typer(help="Project-scoped curation run commands.")
evaluation_app = typer.Typer(help="Evaluation metric commands.")
ontology_app = typer.Typer(help="Project-scoped ontology/ODK commands.")
app.add_typer(literature_app, name="literature")
app.add_typer(project_app, name="project")
app.add_typer(curation_app, name="curation")
app.add_typer(evaluation_app, name="evaluation")
app.add_typer(ontology_app, name="ontology")
console = Console()


def _session():
    from backend.app.db.session import SessionLocal, ensure_runtime_schema

    ensure_runtime_schema()
    return SessionLocal()


def _literature_project_paths(project_ref: str | None):
    from backend.app.literature.canonical import RepositoryPaths
    from backend.app.projects import get_project

    session = _session()
    try:
        project = get_project(session, project_ref)
        root = Path(project.literature_repository_path or (Path(project.local_path) / "literature"))
        return session, project, RepositoryPaths.from_root(root)
    except Exception:
        session.close()
        raise


@project_app.command("create")
def project_create(
    name: str = typer.Option(..., help="Project name."),
    ontology_id: str = typer.Option(..., help="Ontology ID, e.g. ppo."),
    ontology_title: str | None = typer.Option(None, help="Human-readable ontology title."),
    base_iri: str | None = typer.Option(None, help="Ontology base IRI."),
    github_url: str | None = typer.Option(None, help="GitHub repository URL or name."),
    local_workspace_path: Path = typer.Option(..., help="Workspace where projects/<slug> is created."),
    zotero_source_path: str | None = typer.Option(None, help="Local Zotero storage/literature source path."),
    odk_repo_path: str | None = typer.Option(None, help="Existing or planned ODK repository path."),
    term_id_pattern: str | None = typer.Option(None, help="Term ID pattern, e.g. PPO_0000001."),
    description: str | None = typer.Option(None, help="Optional project description."),
) -> None:
    """Create a project folder structure and make it active."""
    from backend.app.projects import create_project, project_payload

    with _session() as session:
        project = create_project(
            session,
            name=name,
            ontology_id=ontology_id,
            ontology_title=ontology_title,
            base_iri=base_iri,
            local_workspace_path=local_workspace_path,
            github_url=github_url,
            zotero_literature_source_path=zotero_source_path,
            odk_repo_path=odk_repo_path,
            term_id_pattern=term_id_pattern,
            description=description,
        )
        payload = project_payload(project)
    console.print(f"[green]Created active project:[/green] {payload['slug']}")
    console.print(payload["local_path"])


@project_app.command("list")
def project_list() -> None:
    """List projects."""
    from sqlalchemy import select

    from backend.app.models.db import Project

    with _session() as session:
        projects = session.scalars(select(Project).order_by(Project.active.desc(), Project.name)).all()
        for project in projects:
            marker = "*" if project.active else " "
            console.print(f"{marker} {project.id}: {project.slug} | {project.name} | {project.local_path}")


@project_app.command("select")
def project_select(project: str = typer.Argument(..., help="Project id or slug.")) -> None:
    """Select the active project."""
    from backend.app.projects import select_project

    with _session() as session:
        selected = select_project(session, project)
    console.print(f"[green]Active project:[/green] {selected.slug}")


@project_app.command("show")
def project_show(project: str | None = typer.Argument(None, help="Project id or slug; defaults to active.")) -> None:
    """Show project metadata."""
    import json

    from backend.app.projects import get_project, project_payload

    with _session() as session:
        selected = get_project(session, project)
        payload = project_payload(selected)
    console.print(json.dumps(payload, indent=2))


@curation_app.command("run")
def curation_run(
    project: str | None = typer.Option(None, "--project", help="Project id or slug; defaults to active."),
    strategy: str = typer.Option("literature_plus_ontology", help="Prompt strategy."),
    name: str | None = typer.Option(None, help="Run name."),
    model: str | None = typer.Option(None, help="Model name/settings label."),
    prompt_file: Path | None = typer.Option(None, help="Prompt text file."),
    raw_output_file: Path | None = typer.Option(None, help="Optional LLM JSON output to parse into suggestions."),
) -> None:
    """Create a project curation run and optionally parse raw suggestion JSON."""
    from backend.app.projects import create_curation_run, get_project, persist_suggestions

    prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file else None
    raw_output = raw_output_file.read_text(encoding="utf-8") if raw_output_file else None
    with _session() as session:
        selected = get_project(session, project)
        run = create_curation_run(
            session,
            selected,
            name=name,
            strategy=strategy,
            model=model,
            prompt_text=prompt_text,
            raw_output=raw_output,
        )
        count = 0
        warning = None
        if raw_output:
            count, warning = persist_suggestions(session, run, raw_output)
    console.print(f"[green]Curation run:[/green] {run.id} ({run.prompt_strategy})")
    console.print(f"[bold]Parsed suggestions:[/bold] {count}")
    if warning:
        console.print(f"[yellow]{warning}[/yellow]")


@curation_app.command("list-runs")
def curation_list_runs(project: str | None = typer.Option(None, "--project", help="Project id or slug.")) -> None:
    """List curation runs for a project."""
    from sqlalchemy import select

    from backend.app.models.db import CurationRun
    from backend.app.projects import get_project

    with _session() as session:
        selected = get_project(session, project)
        runs = session.scalars(
            select(CurationRun).where(CurationRun.project_id == selected.id).order_by(CurationRun.created_at.desc())
        ).all()
        for run in runs:
            console.print(f"{run.id}: {run.name} | {run.prompt_strategy} | {run.status}")


@curation_app.command("review-summary")
def curation_review_summary(project: str | None = typer.Option(None, "--project", help="Project id or slug.")) -> None:
    """Show review counts for a project."""
    from backend.app.projects import compute_evaluation, get_project

    with _session() as session:
        selected = get_project(session, project)
        result = compute_evaluation(session, selected)
    console.print(result["metrics"])


@curation_app.command("review")
def curation_review(
    suggestion_id: int = typer.Argument(..., help="Suggestion id."),
    status: str = typer.Option(..., help="accepted, edited, rejected, duplicate, unsupported, or further_review."),
    reviewer: str | None = typer.Option(None, help="Reviewer name."),
    comment: str | None = typer.Option(None, help="Review comment."),
    review_time_seconds: int | None = typer.Option(None, help="Review effort in seconds."),
) -> None:
    """Annotate a suggestion with a review decision."""
    from backend.app.models.db import Suggestion
    from backend.app.projects import add_review

    with _session() as session:
        suggestion = session.get(Suggestion, suggestion_id)
        if suggestion is None:
            raise typer.BadParameter(f"Suggestion not found: {suggestion_id}")
        review = add_review(
            session,
            suggestion,
            status=status,
            reviewer=reviewer,
            comment=comment,
            review_time_seconds=review_time_seconds,
        )
    console.print(f"[green]Reviewed suggestion {suggestion_id}:[/green] {review.status}")


@evaluation_app.command("compute")
def evaluation_compute(
    project: str | None = typer.Option(None, "--project", help="Project id or slug."),
    run: int | None = typer.Option(None, "--run", help="Optional curation run id."),
) -> None:
    """Compute reproducible evaluation metrics from stored reviews."""
    import json

    from backend.app.projects import compute_evaluation, get_project

    with _session() as session:
        selected = get_project(session, project)
        result = compute_evaluation(session, selected, run)
    console.print(json.dumps(result["metrics"], indent=2))


@evaluation_app.command("compare")
def evaluation_compare(
    project: str | None = typer.Option(None, "--project", help="Project id or slug."),
    runs: list[int] = typer.Option(..., "--runs", help="Two run ids to compare."),
) -> None:
    """Compare two curation runs by label and relation overlap."""
    import json

    from backend.app.projects import compare_runs, get_project

    if len(runs) != 2:
        raise typer.BadParameter("Pass exactly two --runs values.")
    with _session() as session:
        selected = get_project(session, project)
        result = compare_runs(session, selected, runs[0], runs[1])
    console.print(json.dumps(result, indent=2))


@evaluation_app.command("export")
def evaluation_export(
    project: str | None = typer.Option(None, "--project", help="Project id or slug."),
    output: Path | None = typer.Option(None, help="Output JSON path."),
) -> None:
    """Export evaluation metrics as JSON."""
    import json

    from backend.app.projects import compute_evaluation, get_project

    with _session() as session:
        selected = get_project(session, project)
        result = compute_evaluation(session, selected)
    text = json.dumps(result, indent=2)
    if output:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]Wrote:[/green] {output}")
    else:
        console.print(text)


@ontology_app.command("validate")
def ontology_validate(project: str | None = typer.Option(None, "--project", help="Project id or slug.")) -> None:
    """Validate project ODK path metadata and required files."""
    import json

    from backend.app.projects import get_project, validate_project_odk

    with _session() as session:
        selected = get_project(session, project)
        result = validate_project_odk(session, selected)
    console.print(json.dumps(result, indent=2))


@ontology_app.command("export-templates")
def ontology_export_templates(
    project: str | None = typer.Option(None, "--project", help="Project id or slug."),
    output: Path | None = typer.Option(None, help="Output TSV path; defaults to project curation exports folder."),
    include_further_review: bool = typer.Option(False, help="Include further_review suggestions explicitly."),
) -> None:
    """Export accepted/edited project suggestions to a ROBOT-like TSV."""
    from backend.app.projects import export_suggestions_tsv, get_project, project_layout

    with _session() as session:
        selected = get_project(session, project)
        content = export_suggestions_tsv(session, selected, include_further_review)
        target = output or (project_layout(Path(selected.local_path))["curation_exports"] / "accepted_suggestions.robot.tsv")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    console.print(f"[green]Wrote:[/green] {target}")


@ontology_app.command("init-odk")
def ontology_init_odk(project: str | None = typer.Option(None, "--project", help="Project id or slug.")) -> None:
    """Initialize the local ODK folder placeholder for a project."""
    from backend.app.projects import get_project, project_layout

    with _session() as session:
        selected = get_project(session, project)
        path = Path(selected.odk_repo_path or project_layout(Path(selected.local_path))["ontology_odk"])
        path.mkdir(parents=True, exist_ok=True)
        selected.odk_repo_path = str(path)
        session.commit()
    console.print(f"[green]ODK folder ready:[/green] {path}")


@ontology_app.command("build")
def ontology_build(project: str | None = typer.Option(None, "--project", help="Project id or slug.")) -> None:
    """Log a requested ODK build operation without running destructive commands."""
    from backend.app.projects import get_project, log_odk_operation

    with _session() as session:
        selected = get_project(session, project)
        log_odk_operation(
            session,
            selected,
            operation="build_requested",
            command="make all",
            working_directory=selected.odk_repo_path,
            status="pending_manual_run",
        )
    console.print("[yellow]Build command logged. Run explicit project ODK commands from the UI/CLI when configured.[/yellow]")


@ontology_app.command("test")
def ontology_test(project: str | None = typer.Option(None, "--project", help="Project id or slug.")) -> None:
    """Log a requested ODK test operation without running destructive commands."""
    from backend.app.projects import get_project, log_odk_operation

    with _session() as session:
        selected = get_project(session, project)
        log_odk_operation(
            session,
            selected,
            operation="test_requested",
            command="make test",
            working_directory=selected.odk_repo_path,
            status="pending_manual_run",
        )
    console.print("[yellow]Test command logged. Configure safe execution before running external ODK commands.[/yellow]")


@app.command()
def doctor() -> None:
    """Check local configuration and ODK paths."""
    settings = get_settings()
    console.print(f"[bold]App:[/bold] {settings.app_name}")
    console.print(f"[bold]Database:[/bold] {settings.database_url}")
    console.print(f"[bold]ODK home:[/bold] {settings.odk_home}")
    console.print(f"[bold]ODK home exists:[/bold] {settings.odk_home.exists()}")
    console.print(f"[bold]Ontology repo:[/bold] {settings.ontology_repo or '(not configured)'}")


@app.command("odk-preview")
def odk_preview(
    ontology_repo: Path | None = typer.Option(None, help="Path to an ODK-managed ontology repo."),
) -> None:
    """Show where approved ROBOT templates would be exported."""
    settings = get_settings()
    repo = ontology_repo or settings.ontology_repo
    if repo is None:
        raise typer.BadParameter("Set OCA_ONTOLOGY_REPO or pass --ontology-repo.")

    config = OdkProjectConfig(
        repo_path=repo,
        template_dir=settings.template_dir,
        default_template_file=settings.default_template_file,
    )
    console.print(preview_export_path(config))


@app.command("odk-apply-approved")
def odk_apply_approved(
    dry_run: bool = typer.Option(True, help="Plan the workflow without writing, validating, or uploading."),
    production: bool = typer.Option(False, help="Allow real implementation, validation, and upload."),
    suggestion_file: Path | None = typer.Option(
        None,
        help="Optional ontology-suggestion JSON file to reference in the ODK workflow audit.",
    ),
) -> None:
    """Implement approved candidates, validate ODK output, then upload only after success."""
    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.odk.workflow import config_from_settings, run_approved_candidate_workflow

    if not dry_run and not production:
        raise typer.BadParameter("Pass --production to disable dry-run and allow validation/upload.")
    ensure_runtime_schema()
    config = config_from_settings(dry_run=dry_run or not production, suggestion_file=suggestion_file)
    with SessionLocal() as session:
        result = run_approved_candidate_workflow(session, config=config)
    console.print(f"[bold]Dry run:[/bold] {'yes' if result.dry_run else 'no'}")
    console.print(f"[bold]Accepted candidates:[/bold] {len(result.accepted_candidate_ids)}")
    console.print(f"[bold]Skipped candidates:[/bold] {len(result.skipped_candidate_ids)}")
    if result.implemented_path:
        console.print(f"[bold]Implemented path:[/bold] {result.implemented_path}")
    if result.validation:
        console.print(f"[bold]Validation exit code:[/bold] {result.validation.returncode}")
    if result.upload and result.upload.commit_url:
        console.print(f"[bold]Upload commit:[/bold] {result.upload.commit_url}")
    if result.suggestion_file:
        console.print(f"[bold]Suggestion file:[/bold] {result.suggestion_file}")
    console.print(result.message)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("llm-ontology-suggestions")
def llm_ontology_suggestions(
    dry_run: bool = typer.Option(True, help="Write a traceable prompt/export without calling the LLM."),
    output: Path | None = typer.Option(None, help="Output JSON trace path."),
    repository_path: Path | None = typer.Option(None, help="Override the literature Markdown repository path."),
) -> None:
    """Run or dry-run the ontology suggestion prompt against the literature repository."""
    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.llm.ontology_suggestions import run_ontology_suggestion_test
    from backend.app.services.runtime_config import llm_config

    ensure_runtime_schema()
    with SessionLocal() as session:
        config = llm_config(session)
        try:
            result = run_ontology_suggestion_test(
                config=config,
                repository_path=repository_path,
                output_path=output,
                dry_run=dry_run,
            )
        except Exception as exc:
            raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]{result.message}[/green]")
    console.print(f"[bold]Dry run:[/bold] {'yes' if result.dry_run else 'no'}")
    console.print(f"[bold]Literature records:[/bold] {result.literature_count}")
    console.print(f"[bold]Suggestions:[/bold] {result.suggestion_count}")
    console.print(f"[bold]Trace output:[/bold] {result.output_path}")


@app.command("llm-test")
def llm_test() -> None:
    """Test the configured LLM provider with a tiny prompt."""
    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.llm.clients import test_llm_connection
    from backend.app.services.runtime_config import llm_config

    ensure_runtime_schema()
    with SessionLocal() as session:
        result = test_llm_connection(llm_config(session))
    console.print(f"[bold]Provider:[/bold] {result.provider or '(not configured)'}")
    console.print(f"[bold]Provider key:[/bold] {result.provider_key or '(not configured)'}")
    console.print(f"[bold]Model:[/bold] {result.model or '(default)'}")
    console.print(f"[bold]API key found:[/bold] {'yes' if result.api_key_found else 'no'}")
    console.print(f"[bold]API key source:[/bold] {result.api_key_source or '(none)'}")
    console.print(f"[bold]Status:[/bold] {result.status}")
    if result.latency_ms is not None:
        console.print(f"[bold]Latency:[/bold] {result.latency_ms} ms")
    if result.response_preview:
        console.print(f"[bold]Response:[/bold] {result.response_preview}")
    if not result.ok:
        console.print(f"[red]{result.error or 'LLM test failed.'}[/red]")
        raise typer.Exit(code=1)
    console.print("[green]LLM connection test succeeded.[/green]")


@app.command()
def ingest(
    literature_dir: Path = typer.Argument(..., help="Directory containing literature files to ingest."),
) -> None:
    """Ingest literature files into the Ontology Curation Assistant."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.literature.exporter import refresh_literature_markdown_repository
    from backend.app.models.db import LiteratureDocument

    if not literature_dir.exists():
        raise typer.BadParameter(f"Path does not exist: {literature_dir}")

    if not literature_dir.is_dir():
        raise typer.BadParameter(f"Path is not a directory: {literature_dir}")

    ensure_runtime_schema()

    files = [
        path
        for path in literature_dir.rglob("*")
        if path.is_file()
    ]

    if not files:
        console.print(f"[yellow]No files found in:[/yellow] {literature_dir}")
        return

    inserted = 0
    skipped = 0

    with SessionLocal() as session:
        for path in files:
            resolved_path = str(path.resolve())

            existing = session.scalar(
                select(LiteratureDocument).where(LiteratureDocument.path == resolved_path)
            )
            if existing is not None:
                skipped += 1
                continue

            session.add(LiteratureDocument.from_path(path))

            try:
                session.commit()
                inserted += 1
                console.print(f"[green]ingested[/green] {path}")
            except IntegrityError:
                session.rollback()
                skipped += 1
                console.print(f"[yellow]skipped duplicate[/yellow] {path}")

        markdown_paths = refresh_literature_markdown_repository(session)

    console.print(f"[bold]Inserted:[/bold] {inserted}")
    console.print(f"[bold]Skipped:[/bold] {skipped}")
    console.print(f"[bold]Markdown files refreshed:[/bold] {len(markdown_paths)}")
    

@app.command("literature-list")
def literature_list() -> None:
    """List ingested literature documents."""
    from sqlalchemy import select

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.models.db import LiteratureDocument, LiteratureSource

    ensure_runtime_schema()

    with SessionLocal() as session:
        documents = session.scalars(
            select(LiteratureDocument).order_by(LiteratureDocument.id)
        ).all()
        source_ids = {document.source_id for document in documents if document.source_id is not None}
        sources = {
            source.id: source
            for source in session.scalars(
                select(LiteratureSource).where(LiteratureSource.id.in_(source_ids))
            ).all()
        } if source_ids else {}

    if not documents:
        console.print("[yellow]No literature documents found.[/yellow]")
        return

    for doc in documents:
        content_length = len(doc.content or "")
        source = sources.get(doc.source_id)
        source_text = ""
        if source is not None:
            label = source.citation_key or source.provider_item_key or str(source.id)
            source_text = f", source={label}"
        console.print(
            f"[bold]{doc.id}[/bold] {doc.filename} "
            f"({doc.suffix}, {doc.size_bytes} bytes, {content_length} chars{source_text})"
        )
        

@app.command("literature-show")
def literature_show(
    document_id: int = typer.Argument(..., help="ID of the literature document to show."),
    chars: int = typer.Option(2000, help="Number of extracted content characters to show."),
) -> None:
    """Show extracted content for one ingested literature document."""
    from sqlalchemy import select

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.models.db import LiteratureDocument

    ensure_runtime_schema()

    with SessionLocal() as session:
        document = session.scalar(
            select(LiteratureDocument).where(LiteratureDocument.id == document_id)
        )

    if document is None:
        raise typer.BadParameter(f"No literature document found with id: {document_id}")

    console.print(f"[bold]ID:[/bold] {document.id}")
    console.print(f"[bold]Filename:[/bold] {document.filename}")
    console.print(f"[bold]Suffix:[/bold] {document.suffix}")
    console.print(f"[bold]Size:[/bold] {document.size_bytes} bytes")
    console.print(f"[bold]Content chars:[/bold] {len(document.content or '')}")
    console.print()

    if not document.content:
        console.print("[yellow]No extracted text content.[/yellow]")
        return

    console.print(document.content[:chars])
    

@literature_app.command("import")
def literature_import(
    project: str | None = typer.Option(None, "--project", help="Project slug; defaults to the active project."),
    zotero_storage: Path | None = typer.Option(None, "--zotero-storage", help="Zotero storage directory."),
    pdf_dir: Path | None = typer.Option(None, "--pdf-dir", help="Local PDF/XML/Markdown directory."),
    overwrite: bool = typer.Option(False, help="Replace generated Markdown even when existing content is more complete."),
    keep_sources: bool = typer.Option(True, "--keep-sources/--no-keep-sources"),
) -> None:
    """Import literature into one project's canonical repository."""
    from backend.app.literature.canonical import import_directory, write_project_settings

    if bool(zotero_storage) == bool(pdf_dir):
        raise typer.BadParameter("Provide exactly one of --zotero-storage or --pdf-dir.")
    session, selected, paths = _literature_project_paths(project)
    try:
        source = zotero_storage or pdf_dir
        assert source is not None
        result = import_directory(paths, source, source_type="zotero_storage" if zotero_storage else "local_pdf_folder", keep_sources=keep_sources, overwrite=overwrite)
        write_project_settings(paths, zotero_storage_path=str(zotero_storage) if zotero_storage else None, literature_source_directory=str(source), keep_temporary_pdfs=keep_sources, overwrite_existing_markdown=overwrite, preserve_curated_metadata=True)
    finally:
        session.close()
    console.print(f"[green]Project:[/green] {selected.slug}")
    console.print(f"Scanned {result.files_scanned}; imported {result.imported}; duplicates reused {result.duplicates}; failed {result.failed}.")
    console.print(f"[green]Combined literature:[/green] {result.combined_output_file}")


@literature_app.command("list")
def literature_project_list(project: str | None = typer.Option(None, "--project")) -> None:
    """List canonical literature for one project."""
    from backend.app.literature.canonical import list_entries

    session, selected, paths = _literature_project_paths(project)
    try:
        entries = list_entries(paths)
    finally:
        session.close()
    console.print(f"[bold]{selected.slug}[/bold]: {len(entries)} canonical paper(s)")
    for item in entries:
        console.print(f"{item['canonical_id']} | {item.get('title')} | PII={item.get('pii') or '-'} | DOI={item.get('doi') or '-'} | {item.get('import_status')}")


@literature_app.command("reset")
def literature_project_reset(
    project: str | None = typer.Option(None, "--project"),
    yes: bool = typer.Option(False, "--yes", help="Confirm reset of only this project's literature repository."),
) -> None:
    """Reset only the selected project's literature repository."""
    from backend.app.literature.canonical import reset_repository

    if not yes:
        raise typer.BadParameter("Pass --yes to confirm the project literature reset.")
    session, selected, paths = _literature_project_paths(project)
    try:
        result = reset_repository(paths)
    finally:
        session.close()
    console.print(f"[green]Reset {selected.slug}:[/green] {result['path']}")


@literature_app.command("deduplicate")
def literature_project_deduplicate(
    project: str | None = typer.Option(None, "--project"),
    apply: bool = typer.Option(False, "--apply", help="Apply after creating a backup."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only (the default)."),
) -> None:
    """Scan or safely merge canonical duplicates."""
    from backend.app.literature.canonical import deduplicate

    session, selected, paths = _literature_project_paths(project)
    try:
        result = deduplicate(paths, apply=apply)
    finally:
        session.close()
    console.print_json(data={"project": selected.slug, **result})


@literature_app.command("build-combined")
def literature_project_build_combined(project: str | None = typer.Option(None, "--project")) -> None:
    """Build clean combined Markdown from canonical papers only."""
    from backend.app.literature.canonical import build_combined

    session, selected, paths = _literature_project_paths(project)
    try:
        count = build_combined(paths)
    finally:
        session.close()
    console.print(f"[green]{paths.combined}[/green] ({count} papers, project {selected.slug})")


@literature_app.command("migrate-old")
def literature_project_migrate_old(
    project: str | None = typer.Option(None, "--project"),
    apply: bool = typer.Option(False, "--apply", help="Apply with backup and archive."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only (the default)."),
) -> None:
    """Plan or apply migration from legacy literature folders."""
    from backend.app.literature.canonical import migrate_old

    session, selected, paths = _literature_project_paths(project)
    try:
        result = migrate_old(paths, apply=apply)
    finally:
        session.close()
    console.print_json(data={"project": selected.slug, **result})


@literature_app.command("pipeline")
def literature_pipeline(
    project: str | None = typer.Option(None, "--project", help="Project slug; defaults to active project when available."),
    zotero_literature_storage_path: Path | None = typer.Option(
        None,
        "--zotero-literature-storage-path",
        "--zotero-storage-dir",
        help="Override configured Zotero literature storage path.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override configured literature base directory."),
    pdf_dir: Path | None = typer.Option(None, help="Override configured imported-PDF directory."),
    generated_md_dir: Path | None = typer.Option(None, help="Override configured generated Markdown directory."),
    papers_dir: Path | None = typer.Option(None, help="Override configured per-paper Markdown directory."),
    combined_output_file: Path | None = typer.Option(None, help="Override configured combined Markdown output file."),
    fuzzy_min_score: float | None = typer.Option(None, help="Override generated/paper title fuzzy-match threshold."),
) -> None:
    """Run the configured Zotero PDF-to-combined-Markdown literature pipeline."""
    from backend.app.literature.pipeline import LiteraturePipelineConfig, literature_pipeline_config_from_settings
    from backend.app.literature.pipeline import run_literature_pipeline

    configured = literature_pipeline_config_from_settings()
    project_session = None
    if base_dir is None:
        try:
            project_session, _, project_paths = _literature_project_paths(project)
            base_dir = project_paths.root
        except LookupError:
            if project is not None:
                raise typer.BadParameter(f"Project not found: {project}")
    effective_base_dir = base_dir or configured.base_dir
    config = LiteraturePipelineConfig(
        zotero_literature_storage_path=(
            zotero_literature_storage_path or configured.zotero_literature_storage_path
        ),
        base_dir=effective_base_dir,
        pdf_dir=pdf_dir or (effective_base_dir / "Paper-PDF" if base_dir else configured.pdf_dir),
        generated_md_dir=generated_md_dir or (
            effective_base_dir / "Markdown" if base_dir else configured.generated_md_dir
        ),
        papers_dir=papers_dir or (effective_base_dir / "papers" if base_dir else configured.papers_dir),
        combined_output_file=combined_output_file or (
            effective_base_dir / "combined_literature.md"
            if base_dir
            else configured.combined_output_file
        ),
        fuzzy_min_score=fuzzy_min_score if fuzzy_min_score is not None else configured.fuzzy_min_score,
    )
    try:
        result = run_literature_pipeline(config)
    except (FileNotFoundError, ImportError, OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        if project_session is not None:
            project_session.close()
    console.print(f"[green]Combined literature Markdown:[/green] {result.combined_output_file}")
    console.print(f"[bold]Copied PDFs:[/bold] {result.copied_pdf_count}")
    console.print(f"[bold]Generated Markdown files:[/bold] {result.converted_markdown_count}")
    console.print(f"[bold]Combined literature records:[/bold] {result.combined_markdown_count}")
    console.print(f"[bold]Skipped paper records:[/bold] {result.skipped_paper_count}")
    if result.extraction_report_file:
        console.print(f"[bold]Extraction diagnostics:[/bold] {result.extraction_report_file}")


@literature_app.command("reset-repository")
def literature_reset_repository(
    yes: bool = typer.Option(False, "--yes", help="Confirm the literature repository reset."),
) -> None:
    """Reset the per-paper LLM-ready Markdown literature repository."""
    from sqlalchemy import delete

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.literature.repository import reset_literature_repository
    from backend.app.models.db import CandidateTermRecord, ExtractionRun, LiteratureDocument, LiteratureSource

    if not yes:
        raise typer.BadParameter("Pass --yes to confirm the literature repository reset.")
    result = reset_literature_repository()
    if not result.ok:
        console.print(f"[red]{result.message}[/red]")
        raise typer.Exit(code=1)
    ensure_runtime_schema()
    with SessionLocal() as session:
        session.execute(delete(CandidateTermRecord))
        session.execute(delete(ExtractionRun))
        session.execute(delete(LiteratureDocument))
        session.execute(delete(LiteratureSource))
        session.commit()
    console.print(f"[green]{result.message}[/green]")
    for item in result.deleted:
        console.print(f"deleted {item}")


def _find_literature_markdown_by_id(paper_id: str) -> Path:
    from backend.app.literature.repository import load_literature_markdown

    root = Path(get_settings().literature_repository_path)
    for path in sorted(root.rglob("*.md")) if root.exists() else []:
        if {"raw", "clean", "context", "reports", "blocked", "combined"} & set(path.relative_to(root).parts):
            continue
        try:
            paper = load_literature_markdown(path)
        except (OSError, ValueError):
            continue
        if paper_id in {str(paper.get("paper_id") or ""), str(paper.get("id") or ""), path.stem}:
            return path
    raise typer.BadParameter(f"No literature Markdown record found for paper id: {paper_id}")


@literature_app.command("doctor")
def literature_doctor() -> None:
    """Report local PDF/Markdown extractor availability."""
    from backend.app.literature.quality import extractor_availability

    for name, available in extractor_availability().to_dict().items():
        console.print(f"[bold]{name}:[/bold] {'available' if available else 'missing'}")


@literature_app.command("validate")
def literature_validate() -> None:
    """Validate the literature repository and print skipped-file diagnostics."""
    from backend.app.literature.repository import validate_literature_repository

    result = validate_literature_repository()
    console.print(f"[bold]Loaded LLM-ready papers:[/bold] {len(result.papers)}")
    console.print(f"[bold]Skipped papers:[/bold] {len(result.skipped_files)}")
    for skipped in result.skipped_files:
        console.print(f"[yellow]skipped[/yellow] {skipped.get('path')}: {skipped.get('error')}")


@literature_app.command("retry-extraction")
def literature_retry_extraction(
    paper_id: str = typer.Argument(..., help="Canonical paper id, legacy id, or Markdown stem."),
    engine: str = typer.Option(..., help="Extractor engine to record for retry, e.g. grobid, docling, marker, pymupdf."),
) -> None:
    """Retry or re-score a literature extraction with a selected engine marker."""
    from backend.app.literature.repository import retry_literature_extraction

    path = _find_literature_markdown_by_id(paper_id)
    paper = retry_literature_extraction(path, engine=engine)
    console.print(f"[green]Retried extraction:[/green] {paper.get('paper_id') or paper.get('id')} via {engine}")


@literature_app.command("regenerate-clean")
def literature_regenerate_clean(
    paper_id: str = typer.Argument(..., help="Canonical paper id, legacy id, or Markdown stem."),
) -> None:
    """Regenerate the clean Markdown artifact for one literature record."""
    from backend.app.literature.repository import regenerate_clean_markdown

    paper = regenerate_clean_markdown(_find_literature_markdown_by_id(paper_id))
    console.print(f"[green]Regenerated clean Markdown:[/green] {paper.get('clean_markdown_file')}")


@literature_app.command("regenerate-context")
def literature_regenerate_context(
    paper_id: str = typer.Argument(..., help="Canonical paper id, legacy id, or Markdown stem."),
) -> None:
    """Regenerate the LLM-context Markdown artifact for one literature record."""
    from backend.app.literature.repository import regenerate_llm_context

    paper = regenerate_llm_context(_find_literature_markdown_by_id(paper_id))
    console.print(f"[green]Regenerated LLM context:[/green] {paper.get('llm_context_file')}")


@literature_app.command("build-combined-context")
def literature_build_combined_context() -> None:
    """Build role-specific combined context files and the excluded-report file."""
    from backend.app.literature.repository import build_combined_context_files

    result = build_combined_context_files()
    console.print(f"[green]Domain context:[/green] {result.domain_context_file} ({result.domain_count})")
    console.print(f"[green]Review context:[/green] {result.review_context_file} ({result.review_count})")
    console.print(f"[green]Methodology context:[/green] {result.methodology_context_file} ({result.methodology_count})")
    console.print(f"[yellow]Excluded report:[/yellow] {result.excluded_report_file} ({result.excluded_count})")


@literature_app.command("report")
def literature_report() -> None:
    """Print canonical literature state and quality counts."""
    from backend.app.literature.repository import literature_repository_report

    report = literature_repository_report()
    console.print(f"[bold]Papers:[/bold] {report['paper_count']}")
    for category, counts in report["counts"].items():
        console.print(f"[bold]{category}[/bold]")
        for name, count in sorted(counts.items()):
            console.print(f"  {name}: {count}")


@app.command("extract-candidates")
def extract_candidates(
    document_id: int = typer.Argument(..., help="ID of the literature document to extract from."),
    prompt_out: Path | None = typer.Option(
        None,
        help="Write the extraction prompt to this file and exit.",
    ),
    mock_output: Path | None = typer.Option(
        None,
        help="Load a mock LLM JSON response from this file instead of calling a provider.",
    ),
    dry_run: bool = typer.Option(
        False,
        help="Validate and print candidates without persisting them.",
    ),
    chars: int = typer.Option(
        12000,
        help="Maximum number of document characters to include in the prompt.",
    ),
) -> None:
    """Extract structured ontology candidate terms from an ingested document."""
    from sqlalchemy import select

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.extraction.parser import CandidateExtractionParseError, parse_candidate_response
    from backend.app.extraction.prompts import build_candidate_extraction_prompt
    from backend.app.extraction.service import persist_candidates
    from backend.app.models.db import LiteratureDocument

    ensure_runtime_schema()
    settings = get_settings()

    with SessionLocal() as session:
        document = session.scalar(
            select(LiteratureDocument).where(LiteratureDocument.id == document_id)
        )

    if document is None:
        raise typer.BadParameter(f"No literature document found with id: {document_id}")

    if not document.content:
        console.print("[yellow]No extracted text content available.[/yellow]")
        return

    prompt = build_candidate_extraction_prompt(
        document.content,
        document_id=document.id,
        filename=document.filename,
        chars=chars,
    )

    if prompt_out is not None:
        prompt_out.write_text(prompt, encoding="utf-8")
        console.print(f"[green]Wrote prompt:[/green] {prompt_out}")
        return

    if mock_output is None:
        if not settings.llm_provider:
            raise typer.BadParameter(
                "No LLM provider configured. Use --prompt-out or --mock-output, "
                "or configure OCA_LLM_PROVIDER."
            )
        raise typer.BadParameter(
            f"LLM provider '{settings.llm_provider}' is configured, but no provider "
            "implementation is available yet. Use --prompt-out or --mock-output."
        )

    if not mock_output.exists():
        raise typer.BadParameter(f"Mock output file does not exist: {mock_output}")

    raw_response = mock_output.read_text(encoding="utf-8")

    try:
        response = parse_candidate_response(raw_response)
    except CandidateExtractionParseError as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print(f"[bold]Document:[/bold] {document.filename}")
    console.print(f"[bold]Validated candidates:[/bold] {len(response.candidates)}")

    if dry_run:
        for candidate in response.candidates:
            quote = candidate.evidence[0].quoted_text if candidate.evidence else ""
            console.print(
                f"- {candidate.label} "
                f"[confidence={candidate.confidence_score:.2f}; evidence={quote[:80]}]"
            )
        console.print("[yellow]Dry run: no candidates persisted.[/yellow]")
        return

    with SessionLocal() as session:
        inserted, skipped = persist_candidates(
            session,
            document_id=document.id,
            response=response,
            provider="mock",
            model=settings.llm_model or "mock-output",
            raw_response=raw_response,
        )

    console.print(f"[bold]Inserted:[/bold] {inserted}")
    console.print(f"[bold]Skipped:[/bold] {skipped}")


@app.command("candidates-list")
def candidates_list() -> None:
    """List persisted candidate ontology terms."""
    import json

    from sqlalchemy import select

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.models.db import CandidateTermRecord

    ensure_runtime_schema()

    with SessionLocal() as session:
        candidates = session.scalars(
            select(CandidateTermRecord).order_by(CandidateTermRecord.id)
        ).all()

    if not candidates:
        console.print("[yellow]No candidate terms found.[/yellow]")
        return

    for candidate in candidates:
        evidence = json.loads(candidate.evidence_json or "[]")
        preview = evidence[0].get("quoted_text", "") if evidence else ""
        console.print(
            f"[bold]{candidate.id}[/bold] {candidate.label} "
            f"(confidence={candidate.confidence_score:.2f}, "
            f"status={candidate.review_status}, document={candidate.document_id}) "
            f"{preview[:80]}"
        )


@app.command("candidate-show")
def candidate_show(
    candidate_id_or_db_id: str = typer.Argument(..., help="Candidate database id or candidate_id."),
) -> None:
    """Show full details for one persisted candidate ontology term."""
    import json

    from sqlalchemy import select

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.models.db import CandidateTermRecord

    ensure_runtime_schema()

    with SessionLocal() as session:
        if candidate_id_or_db_id.isdigit():
            candidate = session.scalar(
                select(CandidateTermRecord).where(
                    CandidateTermRecord.id == int(candidate_id_or_db_id)
                )
            )
        else:
            candidate = session.scalar(
                select(CandidateTermRecord).where(
                    CandidateTermRecord.candidate_id == candidate_id_or_db_id
                )
            )

    if candidate is None:
        raise typer.BadParameter(f"No candidate term found with id: {candidate_id_or_db_id}")

    synonyms = json.loads(candidate.synonyms_json or "[]")
    evidence = json.loads(candidate.evidence_json or "[]")

    console.print(f"[bold]ID:[/bold] {candidate.id}")
    console.print(f"[bold]Candidate ID:[/bold] {candidate.candidate_id}")
    console.print(f"[bold]Label:[/bold] {candidate.label}")
    console.print(f"[bold]Definition:[/bold] {candidate.proposed_definition or ''}")
    console.print(f"[bold]Synonyms:[/bold] {', '.join(synonyms) if synonyms else ''}")
    console.print(f"[bold]Proposed parent:[/bold] {candidate.proposed_parent or ''}")
    console.print(f"[bold]Confidence:[/bold] {candidate.confidence_score:.2f}")
    console.print(f"[bold]Review status:[/bold] {candidate.review_status}")
    console.print(f"[bold]Source document ID:[/bold] {candidate.document_id}")
    console.print("[bold]Evidence:[/bold]")
    for item in evidence:
        console.print(f"- {item.get('quoted_text', '')}")


@app.command("zotero-import")
def zotero_import(
    metadata_file: Path = typer.Argument(..., help="Zotero/Better BibTeX CSL JSON export file."),
) -> None:
    """Import offline Zotero-style metadata into the local workflow database."""
    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.literature.exporter import refresh_literature_markdown_repository
    from backend.app.models.db import LiteratureSource
    from backend.app.zotero.importer import import_sources

    if not metadata_file.exists():
        raise typer.BadParameter(f"Metadata file does not exist: {metadata_file}")

    ensure_runtime_schema()
    with SessionLocal() as session:
        try:
            result = import_sources(session, metadata_file)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        markdown_paths = refresh_literature_markdown_repository(session)

    # Keep the import above from looking unused to future readers: importing the model
    # registers it with SQLAlchemy metadata before ensure_runtime_schema().
    _ = LiteratureSource
    console.print(f"[bold]Inserted:[/bold] {result.inserted}")
    console.print(f"[bold]Updated:[/bold] {result.updated}")
    console.print(f"[bold]Skipped:[/bold] {result.skipped}")
    console.print(f"[bold]Markdown files refreshed:[/bold] {len(markdown_paths)}")


@app.command("zotero-list")
def zotero_list() -> None:
    """List imported Zotero source records."""
    from sqlalchemy import select

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.models.db import LiteratureSource

    ensure_runtime_schema()
    with SessionLocal() as session:
        sources = session.scalars(select(LiteratureSource).order_by(LiteratureSource.id)).all()

    if not sources:
        console.print("[yellow]No Zotero source records found.[/yellow]")
        return

    for source in sources:
        key = source.citation_key or source.provider_item_key or ""
        year = source.year or ""
        doi = f", DOI={source.doi}" if source.doi else ""
        console.print(f"[bold]{source.id}[/bold] {key} {year} {source.title}{doi}")


@app.command("zotero-show")
def zotero_show(
    source_id: int = typer.Argument(..., help="Imported Zotero source database id."),
) -> None:
    """Show full metadata for one imported Zotero source."""
    import json

    from sqlalchemy import select

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.models.db import LiteratureSource

    ensure_runtime_schema()
    with SessionLocal() as session:
        source = session.scalar(select(LiteratureSource).where(LiteratureSource.id == source_id))

    if source is None:
        raise typer.BadParameter(f"No Zotero source found with id: {source_id}")

    creators = json.loads(source.creators_json or "[]")
    tags = json.loads(source.tags_json or "[]")
    collections = json.loads(source.collections_json or "[]")

    console.print(f"[bold]ID:[/bold] {source.id}")
    console.print(f"[bold]Provider:[/bold] {source.provider}")
    console.print(f"[bold]Provider item key:[/bold] {source.provider_item_key or ''}")
    console.print(f"[bold]Citation key:[/bold] {source.citation_key or ''}")
    console.print(f"[bold]Item type:[/bold] {source.item_type or ''}")
    console.print(f"[bold]Zotero version:[/bold] {source.zotero_version or ''}")
    console.print(f"[bold]Synced at:[/bold] {source.synced_at or ''}")
    console.print(f"[bold]Title:[/bold] {source.title}")
    console.print(f"[bold]Creators:[/bold] {json.dumps(creators)}")
    console.print(f"[bold]Year:[/bold] {source.year or ''}")
    console.print(f"[bold]DOI:[/bold] {source.doi or ''}")
    console.print(f"[bold]URL:[/bold] {source.url or ''}")
    console.print(f"[bold]Abstract:[/bold] {source.abstract or ''}")
    console.print(f"[bold]Tags:[/bold] {', '.join(tags)}")
    console.print(f"[bold]Collections:[/bold] {', '.join(collections)}")


@app.command("zotero-link-documents")
def zotero_link_documents(
    literature_dir: Path = typer.Argument(..., help="Directory containing already ingested files."),
    force: bool = typer.Option(False, help="Relink documents that already have a source."),
) -> None:
    """Conservatively link ingested local documents to imported Zotero records."""
    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.literature.exporter import refresh_literature_markdown_repository
    from backend.app.models.db import LiteratureDocument, LiteratureSource
    from backend.app.zotero.importer import link_documents_to_sources

    if not literature_dir.exists():
        raise typer.BadParameter(f"Path does not exist: {literature_dir}")

    if not literature_dir.is_dir():
        raise typer.BadParameter(f"Path is not a directory: {literature_dir}")

    ensure_runtime_schema()
    with SessionLocal() as session:
        result = link_documents_to_sources(session, literature_dir, force=force)
        markdown_paths = refresh_literature_markdown_repository(session)

    _ = (LiteratureDocument, LiteratureSource)
    console.print(f"[bold]Linked:[/bold] {result.linked}")
    console.print(f"[bold]Skipped:[/bold] {result.skipped}")
    console.print(f"[bold]Ambiguous:[/bold] {result.ambiguous}")
    console.print(f"[bold]Markdown files refreshed:[/bold] {len(markdown_paths)}")


@app.command("zotero-config")
def zotero_config() -> None:
    """Show Zotero API sync configuration without exposing secrets."""
    settings = get_settings()
    console.print(f"[bold]Library type:[/bold] {settings.zotero_library_type or '(not configured)'}")
    console.print(f"[bold]Library ID:[/bold] {settings.zotero_library_id or '(not configured)'}")
    console.print(
        f"[bold]API key configured:[/bold] {'yes' if settings.zotero_api_key else 'no'}"
    )
    console.print(
        f"[bold]Collection key:[/bold] {settings.zotero_collection_key or '(not configured)'}"
    )
    console.print(f"[bold]API base URL:[/bold] {settings.zotero_api_base_url}")


@app.command("zotero-sync")
def zotero_sync(
    collection: str | None = typer.Option(
        None,
        help="Collection key to sync, overriding OCA_ZOTERO_COLLECTION_KEY.",
    ),
    library_type: str | None = typer.Option(
        None,
        help="Library type: user or group.",
    ),
    library_id: str | None = typer.Option(
        None,
        help="Zotero user or group library id.",
    ),
    limit: int | None = typer.Option(
        None,
        help="Maximum number of Zotero items to fetch.",
    ),
    dry_run: bool = typer.Option(
        False,
        help="Fetch and parse items without persisting source records.",
    ),
) -> None:
    """Sync Zotero Web API metadata into the local workflow database."""
    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.literature.exporter import refresh_literature_markdown_repository
    from backend.app.zotero.client import (
        ZoteroApiClient,
        ZoteroApiConfig,
        ZoteroApiError,
    )
    from backend.app.zotero.importer import import_parsed_sources, parse_source_item

    settings = get_settings()
    effective_library_type = library_type or settings.zotero_library_type
    effective_library_id = library_id or settings.zotero_library_id
    effective_collection = collection or settings.zotero_collection_key

    config = ZoteroApiConfig(
        library_type=effective_library_type,
        library_id=effective_library_id,
        api_key=settings.zotero_api_key,
        collection_key=effective_collection,
        base_url=settings.zotero_api_base_url,
    )

    try:
        client = ZoteroApiClient(config)
        items = client.fetch_items(collection_key=effective_collection, limit=limit)
    except ZoteroApiError as exc:
        raise typer.BadParameter(str(exc)) from exc

    sources = []
    skipped = 0
    for item in items:
        source = parse_source_item(item)
        if source is None:
            skipped += 1
            continue
        sources.append(source)

    target = f"{effective_library_type} library {effective_library_id}"
    collection_text = effective_collection or "(whole library)"
    console.print(f"[bold]Zotero sync target:[/bold] {target}")
    console.print(f"[bold]Collection:[/bold] {collection_text}")
    console.print(f"[bold]Fetched items:[/bold] {len(items)}")
    console.print(f"[bold]Importable sources:[/bold] {len(sources)}")
    console.print(f"[bold]Skipped:[/bold] {skipped}")

    if dry_run:
        console.print("[yellow]Dry run: no source records persisted.[/yellow]")
        return

    ensure_runtime_schema()
    with SessionLocal() as session:
        result = import_parsed_sources(session, sources, skipped=skipped, synced=True)
        markdown_paths = refresh_literature_markdown_repository(session)

        # Trigger literature pipeline automatically
        from backend.app.services.runtime_config import literature_pipeline_config
        from backend.app.literature.pipeline import run_literature_pipeline

        pipeline_config = literature_pipeline_config(session)
        try:
            console.print("[bold]Running Zotero PDF literature pipeline...[/bold]")
            pipeline_res = run_literature_pipeline(pipeline_config)
            console.print(
                f"[green]Pipeline complete:[/green] Copied {pipeline_res.copied_pdf_count} PDF(s), "
                f"generated {pipeline_res.converted_markdown_count} Markdown file(s), "
                f"combined {pipeline_res.combined_markdown_count} literature record(s)."
            )
        except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
            console.print(f"[yellow]Warning: Zotero PDF pipeline skipped: {exc}[/yellow]")
        except Exception as exc:
            console.print(f"[red]Error running Zotero PDF pipeline: {exc}[/red]")

    console.print(f"[bold]Inserted:[/bold] {result.inserted}")
    console.print(f"[bold]Updated:[/bold] {result.updated}")
    console.print(f"[bold]Skipped:[/bold] {result.skipped}")
    console.print(f"[bold]Markdown files refreshed:[/bold] {len(markdown_paths)}")
