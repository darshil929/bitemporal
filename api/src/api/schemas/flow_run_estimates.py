"""Bodies of the sync estimate."""

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


class SyncEstimateResponse(BaseModel):
    """The requests a sync over the range would make."""

    model_config = ConfigDict(from_attributes=True)

    requests: RequestsResponse


class RangeRefusedResponse(BaseModel):
    detail: dict[str, str]
