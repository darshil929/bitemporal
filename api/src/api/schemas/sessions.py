"""Bodies of the answers about the person a request acts for."""

from datetime import datetime

from pydantic import BaseModel

from api.services.sessions import EndedReason, Role


class SessionResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: Role
    must_change_password: bool


class SessionEnded(BaseModel):
    """Why the request's session is not running; every field absent where it never was."""

    reason: EndedReason | None
    ended_at: datetime | None
    idle_minutes: int | None
    max_hours: int | None


class NotSignedInResponse(BaseModel):
    detail: SessionEnded
