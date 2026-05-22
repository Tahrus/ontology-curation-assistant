from typer.testing import CliRunner

from backend.app.cli import app


runner = CliRunner()


def test_ingest_missing_directory():
    result = runner.invoke(app, ["ingest", "does-not-exist"])

    assert result.exit_code != 0
    assert "Path does not exist" in result.output


def test_ingest_directory(tmp_path):
    literature_dir = tmp_path / "literature"
    literature_dir.mkdir()
    test_file = literature_dir / "test.txt"
    test_file.write_text("test literature note", encoding="utf-8")

    result = runner.invoke(app, ["ingest", str(literature_dir)])

    assert result.exit_code == 0
    assert "Inserted:" in result.output