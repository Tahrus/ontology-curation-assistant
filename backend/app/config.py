from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(env_prefix="OCA_", env_file=".env", extra="ignore")

    app_name: str = "Ontology Curation Assistant"
    database_url: str = "sqlite:///./oca.sqlite3"
    odk_home: Path = Field(default=Path(r"C:\Users\ge47vob\ontology-development-kit"))
    ontology_repo: Path | None = None
    local_ontology_path: Path = Path(r"C:\Users\ge47vob\ontology-development-kit\target\ppo")
    template_dir: str = "src/ontology/templates"
    default_template_file: str = "ai_approved_terms.tsv"
    git_branch_prefix: str = "ai-curation/"
    require_human_approval: bool = True
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_context_char_limit: int = 200_000
    zotero_library_type: str | None = None
    zotero_library_id: str | None = None
    zotero_api_key: str | None = None
    zotero_collection_key: str | None = None
    zotero_api_base_url: str = "https://api.zotero.org"
    zotero_literature_storage_path: Path | None = Field(
        default=None,
        validation_alias="OCA_ZOTERO_LITERATURE_STORAGE_PATH",
    )
    zotero_linked_attachment_base_dir: Path | None = None
    literature_base_dir: Path = Path("literature")
    literature_pdf_dir: Path = Path("literature") / "Paper-PDF"
    literature_generated_md_dir: Path = Path("literature") / "Markdown"
    literature_repository_path: Path = Path("literature") / "papers"
    literature_combined_output_file: Path = Path("literature") / "combined_literature.md"
    literature_fuzzy_min_score: float = 0.82
    ppo_odk_ontology_path: Path = Field(
        default=Path(r"C:\Users\ge47vob\ontology-development-kit\target\ppo\target\ppo\src\ontology"),
        validation_alias=AliasChoices("PPO_ODK_ONTOLOGY_PATH", "OCA_PPO_ODK_ONTOLOGY_PATH"),
    )
    odk_template_relative_path: str = "templates/ai_approved_terms.tsv"
    odk_validation_command: str = "make test"
    odk_workflow_dry_run: bool = True
    odk_upload_mode: str = "github"
    odk_audit_log_path: Path = Path("logs") / "odk_workflow_audit.jsonl"
    github_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GITHUB_TOKEN", "OCA_GITHUB_TOKEN"),
    )
    github_repository: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GITHUB_REPOSITORY", "OCA_GITHUB_REPOSITORY"),
    )
    github_branch: str = Field(
        default="main",
        validation_alias=AliasChoices("GITHUB_BRANCH", "OCA_GITHUB_BRANCH"),
    )
    github_base_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GITHUB_BASE_PATH", "OCA_GITHUB_BASE_PATH"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
