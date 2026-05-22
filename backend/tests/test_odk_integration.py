from pathlib import Path

from backend.app.odk.integration import OdkProjectConfig, preview_export_path


def test_preview_export_path() -> None:
    config = OdkProjectConfig(repo_path=Path("ontology"))
    assert preview_export_path(config) == Path("ontology/src/ontology/templates/ai_approved_terms.tsv")

