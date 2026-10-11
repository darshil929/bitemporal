"""Bodies of the health and readiness answers."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database_schema: str
    migration: str | None
    expected_migration: str
    reason: str | None
