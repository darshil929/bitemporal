"""Bodies of the data status reads."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.flow_run_estimates import DurationResponse
from api.schemas.flow_run_progress import StageName
from api.schemas.market import Venue


class VenueDayResponse(BaseModel):
    """A venue's latest stored day, whether it passed its checks, and the bars it holds."""

    model_config = ConfigDict(from_attributes=True)

    venue: Venue
    latest_day: date
    is_complete: bool
    bars: int


class LastRunResponse(BaseModel):
    """The newest run of a flow not cancelled: its days, when it ran, how it ended, and the counts
    of what failed or warned. A failed fetch is a day, a range of corporate actions or a list."""

    model_config = ConfigDict(from_attributes=True)

    flow: Literal["bootstrap", "sync"]
    first_day: date
    last_day: date
    started_at: datetime
    ended_at: datetime
    outcome: Literal["succeeded", "failed"]
    checks_passed: int
    failed_steps: list[str]
    failed_stages: list[StageName]
    failed_fetches: int
    failed_checks: int
    warned_checks: int


class RunningSyncResponse(BaseModel):
    """The request waiting or running, its days, and while it runs the stage and the time left."""

    model_config = ConfigDict(from_attributes=True)

    flow: Literal["bootstrap", "sync"]
    first_day: date
    last_day: date
    status: Literal["requested", "running", "cancelling"]
    requested_at: datetime
    started_at: datetime | None
    current_stage: StageName | None
    time_left: DurationResponse | None


class DataStatusResponse(BaseModel):
    """How current the market data is: `unknown` with no run recorded and none running; else the
    first that applies: `failed` when the last run failed; `stale` when a weekday after the day the
    pages show has ended without figures and its files were due by 07:30 India time the next
    morning, a weekday both venues' price files answered not published excepted; `updating` while a
    request waits or runs; else `fresh`."""

    model_config = ConfigDict(from_attributes=True)

    state: Literal["fresh", "stale", "updating", "failed", "unknown"]
    published_day: date | None
    venues: list[VenueDayResponse]
    last_run: LastRunResponse | None
    stale_since: date | None
    days_never_asked: int
    running: RunningSyncResponse | None
