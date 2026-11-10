"""Bodies of the sync and bootstrap estimates."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class DurationResponse(BaseModel):
    """A length of time in seconds, and in whole minutes rounded up."""

    model_config = ConfigDict(from_attributes=True)

    seconds: int
    minutes: int


class SourceDaysResponse(BaseModel):
    """A daily file's days in a range: those held, and those a run would ask for."""

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    days: int
    held: int
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
    features, other) and in all, and each of those runs' whole duration, newest first."""

    model_config = ConfigDict(from_attributes=True)

    stages: dict[str, DurationResponse]
    duration: DurationResponse
    last_runs: list[DurationResponse]


class SyncEstimateResponse(BaseModel):
    """A sync's requests over the range and its fixed work; no fixed work before a sync ran."""

    model_config = ConfigDict(from_attributes=True)

    requests: RequestsResponse
    fixed: FixedWorkResponse | None


class BootstrapEstimateResponse(BaseModel):
    """The bootstrap's runs, the two most recent years then the days before, and its fixed work;
    no fixed work before a bootstrap ran."""

    model_config = ConfigDict(from_attributes=True)

    windows: list[RequestsResponse]
    fixed: FixedWorkResponse | None


class RangeRefusedResponse(BaseModel):
    detail: dict[str, str]
