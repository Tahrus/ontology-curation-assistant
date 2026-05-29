from pathlib import Path

import typer
from rich.console import Console

from backend.app.config import get_settings
from backend.app.odk.integration import OdkProjectConfig, preview_export_path


app = typer.Typer(help="Ontology Curation Assistant command line tools.")
console = Console()


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


@app.command()
def ingest(
    literature_dir: Path = typer.Argument(..., help="Directory containing literature files to ingest."),
) -> None:
    """Ingest literature files into the Ontology Curation Assistant."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from backend.app.db.session import SessionLocal, ensure_runtime_schema
    from backend.app.literature.exporter import export_literature_json
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

        export_path = export_literature_json(session)

    console.print(f"[bold]Inserted:[/bold] {inserted}")
    console.print(f"[bold]Skipped:[/bold] {skipped}")
    console.print(f"[bold]Literature JSON:[/bold] {export_path}")
    

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
    from backend.app.literature.exporter import export_literature_json
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
        export_path = export_literature_json(session)

    # Keep the import above from looking unused to future readers: importing the model
    # registers it with SQLAlchemy metadata before ensure_runtime_schema().
    _ = LiteratureSource
    console.print(f"[bold]Inserted:[/bold] {result.inserted}")
    console.print(f"[bold]Updated:[/bold] {result.updated}")
    console.print(f"[bold]Skipped:[/bold] {result.skipped}")
    console.print(f"[bold]Literature JSON:[/bold] {export_path}")


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
    from backend.app.literature.exporter import export_literature_json
    from backend.app.models.db import LiteratureDocument, LiteratureSource
    from backend.app.zotero.importer import link_documents_to_sources

    if not literature_dir.exists():
        raise typer.BadParameter(f"Path does not exist: {literature_dir}")

    if not literature_dir.is_dir():
        raise typer.BadParameter(f"Path is not a directory: {literature_dir}")

    ensure_runtime_schema()
    with SessionLocal() as session:
        result = link_documents_to_sources(session, literature_dir, force=force)
        export_path = export_literature_json(session)

    _ = (LiteratureDocument, LiteratureSource)
    console.print(f"[bold]Linked:[/bold] {result.linked}")
    console.print(f"[bold]Skipped:[/bold] {result.skipped}")
    console.print(f"[bold]Ambiguous:[/bold] {result.ambiguous}")
    console.print(f"[bold]Literature JSON:[/bold] {export_path}")


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
    from backend.app.literature.exporter import export_literature_json
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
        export_path = export_literature_json(session)

    console.print(f"[bold]Inserted:[/bold] {result.inserted}")
    console.print(f"[bold]Updated:[/bold] {result.updated}")
    console.print(f"[bold]Skipped:[/bold] {result.skipped}")
    console.print(f"[bold]Literature JSON:[/bold] {export_path}")
