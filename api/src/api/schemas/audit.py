"""Bodies of the admin action record."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.services.audit import AdminAction


class AuditEntryResponse(BaseModel):
    """An admin action: when, who acted, what they did, on whose account where it names one, and
    the rest of what changed."""

    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    actor_id: int
    actor_name: str
    action: AdminAction
    subject_id: int | None
    subject_name: str | None
    detail: dict[str, Any]
