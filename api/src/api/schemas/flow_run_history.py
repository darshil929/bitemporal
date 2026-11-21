"""Bodies of the run history read."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.flow_run_progress import StageName


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
    duration_seconds: int
    outcome: Literal["succeeded", "failed", "cancelled"]
    counts: dict[str, dict[str, int]]
    checks_passed: int
    failures: list[FailedFetchResponse]
    warned_checks: list[CheckOutcomeResponse]
    failed_checks: list[CheckOutcomeResponse]
    failed_steps: list[str]
    failed_stages: list[StageName]
    unmaterialized: list[str]
    requested_by: str | None


class DayStretchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    first_day: date
    last_day: date


class RunHistoryResponse(BaseModel):
    """The ten newest runs, newest first, each naming the admin who asked for it or none for a run
    started otherwise; the stretches of the history no daily file was asked for, to the latest day
    a run covered; and the instruments the day the pages show holds."""

    model_config = ConfigDict(from_attributes=True)

    runs: list[RecordedRunResponse]
    days_never_asked: list[DayStretchResponse]
    published_instruments: int
