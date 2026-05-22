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

    from backend.app.db.session import Base, SessionLocal, engine
    from backend.app.models.db import LiteratureDocument

    if not literature_dir.exists():
        raise typer.BadParameter(f"Path does not exist: {literature_dir}")

    if not literature_dir.is_dir():
        raise typer.BadParameter(f"Path is not a directory: {literature_dir}")

    Base.metadata.create_all(bind=engine)

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

    console.print(f"[bold]Inserted:[/bold] {inserted}")
    console.print(f"[bold]Skipped:[/bold] {skipped}")
    

@app.command("literature-list")
def literature_list() -> None:
    """List ingested literature documents."""
    from sqlalchemy import select

    from backend.app.db.session import Base, SessionLocal, engine
    from backend.app.models.db import LiteratureDocument

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        documents = session.scalars(
            select(LiteratureDocument).order_by(LiteratureDocument.id)
        ).all()

    if not documents:
        console.print("[yellow]No literature documents found.[/yellow]")
        return

    for doc in documents:
        content_length = len(doc.content or "")
        console.print(
            f"[bold]{doc.id}[/bold] {doc.filename} "
            f"({doc.suffix}, {doc.size_bytes} bytes, {content_length} chars)"
        )
        

@app.command("literature-show")
def literature_show(
    document_id: int = typer.Argument(..., help="ID of the literature document to show."),
    chars: int = typer.Option(2000, help="Number of extracted content characters to show."),
) -> None:
    """Show extracted content for one ingested literature document."""
    from sqlalchemy import select

    from backend.app.db.session import Base, SessionLocal, engine
    from backend.app.models.db import LiteratureDocument

    Base.metadata.create_all(bind=engine)

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
    limit: int = typer.Option(20, help="Maximum number of candidate terms to show."),
) -> None:
    """Extract candidate ontology terms from an ingested literature document."""
    import re
    from collections import Counter

    from sqlalchemy import select

    from backend.app.db.session import Base, SessionLocal, engine
    from backend.app.models.db import LiteratureDocument

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        document = session.scalar(
            select(LiteratureDocument).where(LiteratureDocument.id == document_id)
        )

    if document is None:
        raise typer.BadParameter(f"No literature document found with id: {document_id}")

    if not document.content:
        console.print("[yellow]No extracted text content available.[/yellow]")
        return

    text = document.content

    phrases = re.findall(
        r"\b(?:[a-zA-Z][a-zA-Z\-]+(?:\s+|$)){2,5}",
        text,
    )

    stop_phrases = {
        "the course of",
        "it is shown",
        "there is no",
        "for the better",
        "in terms of",
        "during the course",
    }

    cleaned: list[str] = []
    for phrase in phrases:
        normalized = " ".join(phrase.lower().split())
        if len(normalized) < 8:
            continue
        if normalized in stop_phrases:
            continue
        if normalized.startswith(("the ", "and ", "for ", "with ", "from ")):
            continue
        cleaned.append(normalized)

    counts = Counter(cleaned)

    if not counts:
        console.print("[yellow]No candidate phrases found.[/yellow]")
        return

    console.print(f"[bold]Document:[/bold] {document.filename}")
    console.print(f"[bold]Candidate terms:[/bold]")

    for phrase, count in counts.most_common(limit):
        console.print(f"- {phrase} [count={count}]")