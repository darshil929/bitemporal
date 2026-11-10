"""Bodies of the run history read."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FailedFetchResponse(BaseModel):
    """A day, a range of corporate actions or a list a source could not give, and why."""

    source: str
    key: str
    detail: str


class CheckOutcomeResponse(BaseModel):
    """A check that did not pass, with the rows it found where it records them."""

    name: str
    rows: int | None


class RecordedRunResponse(BaseModel):
    """A finished run of a flow and its report: each source's counts, the checks, and what
    failed."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str
    flow: Literal["bootstrap", "sync"]
    first_day: date
    last_day: date
    started_at: datetime
    ended_at: datetime
    outcome: Literal["succeeded", "failed", "cancelled"]
    counts: dict[str, dict[str, int]]
    checks_passed: int
    failures: list[FailedFetchResponse]
    warned_checks: list[CheckOutcomeResponse]
    failed_checks: list[CheckOutcomeResponse]
    failed_steps: list[str]
    unmaterialized: list[str]


class DayStretchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    first_day: date
    last_day: date


class RunHistoryResponse(BaseModel):
    """The ten newest runs, newest first, and the stretches of the history no daily file was asked
    for, to the latest day a run covered."""

    model_config = ConfigDict(from_attributes=True)

    runs: list[RecordedRunResponse]
    days_never_asked: list[DayStretchResponse]
