"""Bodies of the sync and bootstrap estimates."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DurationResponse(BaseModel):
    """A length of time in seconds, and in whole minutes rounded up."""

    model_config = ConfigDict(from_attributes=True)

    seconds: int
    minutes: int


class SourceDaysResponse(BaseModel):
    """A daily file's days in a range: those held, those not held, those asked again, and their
    sum."""

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    days: int
    held: int
    missing: int
    asked_again: int
    to_request: int


class RequestsResponse(BaseModel):
    """The requests a run over a range makes, one every two seconds per source."""

    model_config = ConfigDict(from_attributes=True)

    first_day: date
    last_day: date
    sources: list[SourceDaysResponse]
    duration: DurationResponse


class FixedWorkResponse(BaseModel):
    """The other steps as the last runs of the flow took them: the median by stage (models,
    features, other) and in all, the shortest and longest of those runs, when they started, and
    each run's whole duration."""

    model_config = ConfigDict(from_attributes=True)

    stages: dict[str, DurationResponse]
    duration: DurationResponse
    last_runs: list[DurationResponse]
    min_run: DurationResponse
    max_run: DurationResponse
    basis_started_at: list[datetime]


class SyncEstimateResponse(BaseModel):
    """A sync's requests over the range, its fixed work, the typical total duration, and the
    calendar bounds; no fixed work or typical total before a sync ran."""

    model_config = ConfigDict(from_attributes=True)

    requests: RequestsResponse
    fixed: FixedWorkResponse | None
    typical: DurationResponse | None
    history_first_day: date | None
    today: date


class BootstrapEstimateResponse(BaseModel):
    """The bootstrap's runs, the two most recent years then the days before, and its fixed work;
    no fixed work before a bootstrap ran."""

    model_config = ConfigDict(from_attributes=True)

    windows: list[RequestsResponse]
    fixed: FixedWorkResponse | None


class RangeRefusedResponse(BaseModel):
    detail: dict[str, str]
