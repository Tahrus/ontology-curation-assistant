from datetime import datetime
from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    event_type: str
    actor: str
    entity_type: str
    entity_id: str
    old_value: str | None = None
    new_value: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

