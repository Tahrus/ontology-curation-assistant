from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.config import get_settings


LOGGER = logging.getLogger(__name__)


def write_audit_event(event_type: str, *, entity_type: str, entity_id: str, details: dict[str, Any]) -> None:
    """Append a secret-safe JSONL audit event for curation and ODK workflow actions."""
    path = get_settings().odk_audit_log_path
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "actor": "system",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": _redact(details),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    LOGGER.info("Audit event written: %s %s", event_type, entity_id)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if _is_secret_key(key) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.casefold()
    return any(marker in lowered for marker in ["token", "secret", "api_key", "password", "credential"])
