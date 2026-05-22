from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(env_prefix="OCA_", env_file=".env", extra="ignore")

    app_name: str = "Ontology Curation Assistant"
    database_url: str = "sqlite:///./oca.sqlite3"
    odk_home: Path = Field(default=Path(r"C:\Users\ge47vob\ontology-development-kit"))
    ontology_repo: Path | None = None
    template_dir: str = "src/ontology/templates"
    default_template_file: str = "ai_approved_terms.tsv"
    git_branch_prefix: str = "ai-curation/"
    require_human_approval: bool = True
    llm_provider: str | None = None
    llm_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

