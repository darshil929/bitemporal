"""Bodies of the session limit settings."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionLimitsResponse(BaseModel):
    """Minutes a session may go unused, hours it may last at most, and when either last changed."""

    model_config = ConfigDict(from_attributes=True)

    session_idle_minutes: int
    session_max_hours: int
    updated_at: datetime


class SessionLimitsChangeRequest(BaseModel):
    """A new idle limit, a new maximum, or both."""

    session_idle_minutes: int | None = Field(default=None, ge=5, le=1440)
    session_max_hours: int | None = Field(default=None, ge=1, le=72)

    @model_validator(mode="after")
    def names_a_limit(self) -> Self:
        if self.session_idle_minutes is None and self.session_max_hours is None:
            raise ValueError("a change names the idle limit, the maximum, or both")
        return self
