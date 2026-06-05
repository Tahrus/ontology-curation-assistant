from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.app.config import get_settings


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitHubExportConfig:
    token: str | None
    repository: str | None
    branch: str
    base_path: str | None = None
    api_base_url: str = "https://api.github.com"


@dataclass(frozen=True)
class GitHubExportResult:
    ok: bool
    message: str
    commit_url: str | None = None
    metadata: dict[str, Any] | None = None


def github_config_from_settings() -> GitHubExportConfig:
    settings = get_settings()
    return GitHubExportConfig(
        token=settings.github_token,
        repository=settings.github_repository,
        branch=settings.github_branch,
        base_path=settings.github_base_path,
    )


def save_generated_ontology_to_github(
    files: dict[str, str | bytes | Path],
    *,
    commit_message: str,
    config: GitHubExportConfig | None = None,
    client: httpx.Client | None = None,
) -> GitHubExportResult:
    """Create or update generated ontology files in a configured GitHub repository."""
    cfg = config or github_config_from_settings()
    validation_error = _validate_config(cfg)
    if validation_error:
        return GitHubExportResult(ok=False, message=validation_error)

    close_client = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        responses = []
        for path, content in files.items():
            github_path = _github_path(path, cfg.base_path)
            existing_sha = _existing_file_sha(http, cfg, github_path)
            payload = {
                "message": commit_message,
                "content": base64.b64encode(_file_bytes(content)).decode("ascii"),
                "branch": cfg.branch,
            }
            if existing_sha:
                payload["sha"] = existing_sha
            response = http.put(
                f"{cfg.api_base_url}/repos/{cfg.repository}/contents/{github_path}",
                headers=_headers(cfg),
                json=payload,
            )
            if response.status_code in {401, 403}:
                return GitHubExportResult(ok=False, message="GitHub authentication failed.")
            if response.status_code == 404:
                return GitHubExportResult(
                    ok=False,
                    message="GitHub repository, branch, or target path was not found.",
                )
            response.raise_for_status()
            responses.append(response.json())
        commit = (responses[-1].get("commit") if responses else {}) or {}
        commit_url = commit.get("html_url") or commit.get("url")
        LOGGER.info("Saved %s generated ontology file(s) to GitHub %s", len(files), cfg.repository)
        return GitHubExportResult(
            ok=True,
            message=f"Saved {len(files)} generated ontology file(s) to GitHub.",
            commit_url=commit_url,
            metadata={"responses": responses},
        )
    except httpx.RequestError as exc:
        LOGGER.exception("GitHub export request failed")
        return GitHubExportResult(ok=False, message=f"GitHub request failed: {exc}")
    except httpx.HTTPStatusError as exc:
        LOGGER.exception("GitHub export failed")
        return GitHubExportResult(ok=False, message=f"GitHub commit failed: {exc.response.text}")
    finally:
        if close_client:
            http.close()


def _validate_config(config: GitHubExportConfig) -> str | None:
    if not config.token:
        return "GITHUB_TOKEN is not configured."
    if not config.repository or "/" not in config.repository:
        return "GITHUB_REPOSITORY must be configured as owner/repo."
    if not config.branch:
        return "GITHUB_BRANCH is not configured."
    return None


def _headers(config: GitHubExportConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_path(path: str, base_path: str | None) -> str:
    clean = str(path).replace("\\", "/").lstrip("/")
    if base_path:
        return f"{base_path.strip('/')}/{clean}"
    return clean


def _file_bytes(content: str | bytes | Path) -> bytes:
    if isinstance(content, Path):
        return content.read_bytes()
    if isinstance(content, bytes):
        return content
    return content.encode("utf-8")


def _existing_file_sha(http: httpx.Client, config: GitHubExportConfig, path: str) -> str | None:
    response = http.get(
        f"{config.api_base_url}/repos/{config.repository}/contents/{path}",
        headers=_headers(config),
        params={"ref": config.branch},
    )
    if response.status_code == 404:
        return None
    if response.status_code in {401, 403}:
        response.raise_for_status()
    response.raise_for_status()
    data = response.json()
    return data.get("sha") if isinstance(data, dict) else None
