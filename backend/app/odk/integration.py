from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OdkProjectConfig:
    repo_path: Path
    template_dir: str = "src/ontology/templates"
    default_template_file: str = "ai_approved_terms.tsv"


def preview_export_path(config: OdkProjectConfig) -> Path:
    """Return the target ROBOT template path for approved AI-assisted terms."""
    return config.repo_path / config.template_dir / config.default_template_file


def build_command_candidates() -> list[str]:
    """Project-specific ODK repos may expose different Make targets."""
    return ["make test", "make prepare_release"]

