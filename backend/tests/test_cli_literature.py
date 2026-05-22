from pathlib import Path

from typer.testing import CliRunner

from backend.app.cli import app


runner = CliRunner()


def test_literature_show_missing_document():
    result = runner.invoke(app, ["literature-show", "999999"])

    assert result.exit_code != 0
    assert "No literature document found" in result.output


def test_ingest_missing_directory():
    result = runner.invoke(app, ["ingest", "does-not-exist"])

    assert result.exit_code != 0
    assert "Path does not exist" in result.output