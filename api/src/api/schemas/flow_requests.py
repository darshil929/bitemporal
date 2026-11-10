"""Bodies of the sync and bootstrap requests."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class SyncRequestBody(BaseModel):
    first_day: date
    last_day: date


class RequestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    first_day: date
    last_day: date
    outcome: Literal["succeeded", "failed", "cancelled"]


class FlowRequestResponse(BaseModel):
    """A request as it stands. `refused` carries the reason and its facts: `flow_running` with the
    running flow's days and start, `migration_behind` with the migration found and expected,
    `dbt_building` with the target. A started request lists each run it took and how it ended."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    flow: Literal["bootstrap", "sync"]
    first_day: date
    last_day: date
    status: Literal["requested", "started", "refused", "finished"]
    requested_by: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    refusal: dict[str, Any] | None
    runs: list[RequestRunResponse]


class RequestPending(BaseModel):
    reason: Literal["request_pending"]
    request_id: int


class RequestPendingResponse(BaseModel):
    detail: RequestPending
