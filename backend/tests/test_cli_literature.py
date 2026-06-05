from typer.testing import CliRunner

from backend.app.cli import app
from backend.app.literature.pipeline import LiteraturePipelineResult


runner = CliRunner()


def test_literature_show_missing_document():
    result = runner.invoke(app, ["literature-show", "999999"])

    assert result.exit_code != 0
    assert "No literature document found" in result.output


def test_ingest_missing_directory():
    result = runner.invoke(app, ["ingest", "does-not-exist"])

    assert result.exit_code != 0
    assert "Path does not exist" in result.output


def test_literature_pipeline_cli_base_dir_restores_expected_subfolders(tmp_path, monkeypatch):
    import backend.app.literature.pipeline as pipeline

    captured = {}

    def fake_run(config):
        captured["config"] = config
        return LiteraturePipelineResult(
            combined_output_file=config.combined_output_file,
            copied_pdf_count=1,
            converted_markdown_count=1,
            failed_pdf_count=0,
            created_paper_markdown_count=1,
            structured_markdown_count=1,
            combined_markdown_count=1,
        )

    monkeypatch.setattr(pipeline, "run_literature_pipeline", fake_run)
    storage = tmp_path / "storage"
    base = tmp_path / "literature-base"

    result = runner.invoke(
        app,
        [
            "literature",
            "pipeline",
            "--zotero-storage-dir",
            str(storage),
            "--base-dir",
            str(base),
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].zotero_literature_storage_path == storage
    assert captured["config"].base_dir == base
    assert captured["config"].pdf_dir == base / "Paper-PDF"
    assert captured["config"].generated_md_dir == base / "Markdown"
    assert captured["config"].papers_dir == base / "papers"
    assert captured["config"].combined_output_file == base / "combined_literature.md"
