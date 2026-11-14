"""Bodies of the run progress read."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.flow_run_estimates import DurationResponse

StageName = Literal[
    "prices", "identity", "delivery", "actions", "names", "models", "features", "checks"
]


class StageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: StageName
    state: Literal["done", "running", "pending", "failed"]


class DayAnswersResponse(BaseModel):
    """Each daily file's answer for a day: succeeded, not_published or failed; a file not yet asked
    for the day is absent."""

    model_config = ConfigDict(from_attributes=True)

    day: date
    outcomes: dict[str, str]


class YearAnswersResponse(BaseModel):
    """The days of a year in the window, and how many each daily file answered."""

    model_config = ConfigDict(from_attributes=True)

    year: int
    days: int
    answered: dict[str, int]


class FailedFetchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    key: str
    detail: str


class FetchesResponse(BaseModel):
    """What the run has fetched in the window it runs: by day up to a month, by year beyond, and
    every slice whose latest answer failed, with its reason."""

    model_config = ConfigDict(from_attributes=True)

    first_day: date
    last_day: date
    days: list[DayAnswersResponse] | None
    years: list[YearAnswersResponse] | None
    failures: list[FailedFetchResponse]


class ProgressResponse(BaseModel):
    """A request's run as it stands: its status, each stage in order, the stage running now, and
    the time left by the steps' medians over the last three runs; no time left once the run ended
    or before any run of the flow was measured."""

    model_config = ConfigDict(from_attributes=True)

    status: Literal[
        "requested", "running", "cancelling", "cancelled", "refused", "succeeded", "failed"
    ]
    stages: list[StageResponse]
    current_stage: StageName | None
    time_left: DurationResponse | None
    fetches: FetchesResponse | None
