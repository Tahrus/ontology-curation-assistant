from __future__ import annotations

import io
import json
import logging
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.github_export import GitHubExportResult, save_generated_ontology_to_github
from backend.app.models.core import ReviewStatus
from backend.app.models.db import CandidateTermRecord
from backend.app.odk.integration import stage_generated_ontology_artifact, write_robot_template


LOGGER = logging.getLogger(__name__)
EXPORTABLE_STATUSES = {ReviewStatus.APPROVED.value, ReviewStatus.APPROVED_WITH_EDITS.value}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class OdkImplementationConfig:
    ontology_path: Path
    template_relative_path: str
    validation_command: str
    audit_log_path: Path
    suggestion_file: Path | None = None
    dry_run: bool = True
    upload_mode: str = "github"
    commit_message: str = "Apply approved ontology candidates"


@dataclass
class OdkWorkflowResult:
    ok: bool
    message: str
    dry_run: bool
    accepted_candidate_ids: list[str] = field(default_factory=list)
    skipped_candidate_ids: list[str] = field(default_factory=list)
    implemented_path: str | None = None
    validation: CommandResult | None = None
    upload: GitHubExportResult | None = None
    audit_log_path: str | None = None
    suggestion_file: str | None = None


CommandRunner = Callable[[str, Path], CommandResult]
Uploader = Callable[[dict[str, Path], str], GitHubExportResult]


def config_from_settings(
    *,
    dry_run: bool | None = None,
    suggestion_file: Path | None = None,
) -> OdkImplementationConfig:
    settings = get_settings()
    return OdkImplementationConfig(
        ontology_path=settings.ppo_odk_ontology_path,
        template_relative_path=settings.odk_template_relative_path,
        validation_command=settings.odk_validation_command,
        audit_log_path=settings.odk_audit_log_path,
        suggestion_file=suggestion_file,
        dry_run=settings.odk_workflow_dry_run if dry_run is None else dry_run,
        upload_mode=settings.odk_upload_mode,
    )


def run_approved_candidate_workflow(
    session: Session,
    *,
    config: OdkImplementationConfig | None = None,
    command_runner: CommandRunner | None = None,
    uploader: Uploader | None = None,
) -> OdkWorkflowResult:
    """Implement approved candidates, validate ODK output, then upload only after success."""
    cfg = config or config_from_settings()
    runner = command_runner or _run_command
    upload = uploader or _github_uploader
    suggestion_file = cfg.suggestion_file.resolve() if cfg.suggestion_file else None
    if suggestion_file is not None and not suggestion_file.exists():
        message = f"ODK workflow suggestion file was not found: {suggestion_file}"
        _audit(cfg, "workflow_stopped", {"reason": message})
        return OdkWorkflowResult(
            ok=False,
            message=message,
            dry_run=cfg.dry_run,
            audit_log_path=str(cfg.audit_log_path),
            suggestion_file=str(suggestion_file),
        )
    accepted = _accepted_candidates(session)
    skipped = _non_accepted_candidates(session)
    _audit(cfg, "workflow_started", {
        "dry_run": cfg.dry_run,
        "accepted_candidate_ids": [candidate.candidate_id for candidate in accepted],
        "skipped_candidate_ids": [candidate.candidate_id for candidate in skipped],
        "upload_mode": cfg.upload_mode,
        "suggestion_file": str(suggestion_file) if suggestion_file else None,
    })

    if not accepted:
        message = "No accepted candidates are available for implementation."
        _audit(cfg, "workflow_stopped", {"reason": message})
        return OdkWorkflowResult(
            ok=False,
            message=message,
            dry_run=cfg.dry_run,
            skipped_candidate_ids=[candidate.candidate_id for candidate in skipped],
            audit_log_path=str(cfg.audit_log_path),
            suggestion_file=str(suggestion_file) if suggestion_file else None,
        )

    template_content = _robot_template_text(accepted)
    if cfg.dry_run:
        _audit(cfg, "dry_run_planned", {
            "template_relative_path": cfg.template_relative_path,
            "validation_command": cfg.validation_command,
            "upload_blocked": True,
        })
        return OdkWorkflowResult(
            ok=True,
            message="Dry run complete. No files were written, validation was not run, and upload was blocked.",
            dry_run=True,
            accepted_candidate_ids=[candidate.candidate_id for candidate in accepted],
            skipped_candidate_ids=[candidate.candidate_id for candidate in skipped],
            audit_log_path=str(cfg.audit_log_path),
            suggestion_file=str(suggestion_file) if suggestion_file else None,
        )

    try:
        implemented_path = stage_generated_ontology_artifact(
            cfg.template_relative_path,
            template_content,
            ontology_path=cfg.ontology_path,
        )
    except (OSError, ValueError, FileNotFoundError, NotADirectoryError) as exc:
        message = f"Could not implement approved candidates: {exc}"
        _audit(cfg, "implementation_failed", {"error": str(exc)})
        LOGGER.exception(message)
        return OdkWorkflowResult(
            ok=False,
            message=message,
            dry_run=False,
            audit_log_path=str(cfg.audit_log_path),
            suggestion_file=str(suggestion_file) if suggestion_file else None,
        )

    for candidate in accepted:
        candidate.review_status = ReviewStatus.IMPLEMENTED.value
    session.commit()
    _audit(cfg, "implemented", {
        "path": str(implemented_path),
        "candidate_ids": [candidate.candidate_id for candidate in accepted],
    })

    validation = runner(cfg.validation_command, cfg.ontology_path)
    _audit(cfg, "validation_finished", {
        "command": cfg.validation_command,
        "returncode": validation.returncode,
        "stdout": validation.stdout[-4000:],
        "stderr": validation.stderr[-4000:],
    })
    if validation.returncode != 0:
        for candidate in accepted:
            candidate.review_status = ReviewStatus.ODK_VALIDATION_FAILED.value
        session.commit()
        message = _validation_failure_message(validation)
        _audit(cfg, "workflow_stopped", {"reason": message, "upload_blocked": True})
        return OdkWorkflowResult(
            ok=False,
            message=message,
            dry_run=False,
            accepted_candidate_ids=[candidate.candidate_id for candidate in accepted],
            skipped_candidate_ids=[candidate.candidate_id for candidate in skipped],
            implemented_path=str(implemented_path),
            validation=validation,
            audit_log_path=str(cfg.audit_log_path),
            suggestion_file=str(suggestion_file) if suggestion_file else None,
        )

    for candidate in accepted:
        candidate.review_status = ReviewStatus.VALIDATED.value
    session.commit()
    _audit(cfg, "validated", {"candidate_ids": [candidate.candidate_id for candidate in accepted]})

    if cfg.upload_mode != "github":
        message = f"Validation succeeded, but upload mode '{cfg.upload_mode}' is not supported."
        _audit(cfg, "upload_skipped", {"reason": message})
        return OdkWorkflowResult(
            ok=False,
            message=message,
            dry_run=False,
            accepted_candidate_ids=[candidate.candidate_id for candidate in accepted],
            skipped_candidate_ids=[candidate.candidate_id for candidate in skipped],
            implemented_path=str(implemented_path),
            validation=validation,
            audit_log_path=str(cfg.audit_log_path),
            suggestion_file=str(suggestion_file) if suggestion_file else None,
        )

    upload_result = upload({cfg.template_relative_path: implemented_path}, cfg.commit_message)
    _audit(cfg, "upload_finished", {
        "ok": upload_result.ok,
        "message": upload_result.message,
        "commit_url": upload_result.commit_url,
    })
    if not upload_result.ok:
        return OdkWorkflowResult(
            ok=False,
            message=f"Validation succeeded, but upload failed: {upload_result.message}",
            dry_run=False,
            accepted_candidate_ids=[candidate.candidate_id for candidate in accepted],
            skipped_candidate_ids=[candidate.candidate_id for candidate in skipped],
            implemented_path=str(implemented_path),
            validation=validation,
            upload=upload_result,
            audit_log_path=str(cfg.audit_log_path),
            suggestion_file=str(suggestion_file) if suggestion_file else None,
        )

    for candidate in accepted:
        candidate.review_status = ReviewStatus.UPLOADED.value
    session.commit()
    _audit(cfg, "workflow_completed", {"commit_url": upload_result.commit_url})
    return OdkWorkflowResult(
        ok=True,
        message="Approved candidates implemented, validated, and uploaded.",
        dry_run=False,
        accepted_candidate_ids=[candidate.candidate_id for candidate in accepted],
        skipped_candidate_ids=[candidate.candidate_id for candidate in skipped],
        implemented_path=str(implemented_path),
        validation=validation,
        upload=upload_result,
        audit_log_path=str(cfg.audit_log_path),
        suggestion_file=str(suggestion_file) if suggestion_file else None,
    )


def _accepted_candidates(session: Session) -> list[CandidateTermRecord]:
    return list(
        session.scalars(
            select(CandidateTermRecord)
            .where(CandidateTermRecord.review_status.in_(sorted(EXPORTABLE_STATUSES)))
            .order_by(CandidateTermRecord.id)
        ).all()
    )


def _non_accepted_candidates(session: Session) -> list[CandidateTermRecord]:
    return list(
        session.scalars(
            select(CandidateTermRecord)
            .where(CandidateTermRecord.review_status.not_in(sorted(EXPORTABLE_STATUSES)))
            .order_by(CandidateTermRecord.id)
        ).all()
    )


def _robot_template_text(candidates: list[CandidateTermRecord]) -> str:
    output = io.StringIO()
    write_robot_template(candidates, output)
    return output.getvalue()


def _run_command(command: str, cwd: Path) -> CommandResult:
    args = shlex.split(command, posix=False)
    completed = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _github_uploader(files: dict[str, Path], commit_message: str) -> GitHubExportResult:
    return save_generated_ontology_to_github(files, commit_message=commit_message)


def _validation_failure_message(result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or "no command output"
    return f"ODK validation failed with exit code {result.returncode}: {detail}"


def _audit(config: OdkImplementationConfig, event: str, payload: dict) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "payload": payload,
    }
    config.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    with config.audit_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    LOGGER.info("ODK workflow event: %s", event)
