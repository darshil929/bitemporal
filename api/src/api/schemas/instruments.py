"""Bodies of the instrument reads."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.market import Venue

ClosureReason = Literal["delisted", "renamed", "merged", "superseded"]


class ListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exchange: Venue
    local_symbol: str
    scrip_code: str | None
    listing_date: date
    delisting_date: date | None
    closure_reason: ClosureReason | None


class InstrumentResponse(BaseModel):
    """An instrument under the names a reader knows it by, with every stretch it was listed for;
    `superseded_by` is the ISIN that took it over at a change of face value, `primary_venue` the
    venue its pages open on, absent where no daily features were computed for it."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    name: str
    display_name: str
    instrument_type: str
    superseded_by: str | None
    primary_venue: Venue | None
    venues: list[Venue]
    is_single_listed: bool
    listings: list[ListingResponse]


class InstrumentMatchResponse(BaseModel):
    """An instrument a search found, under the ISIN it trades under now, with the symbol a reader
    knows it by and the venues it is listed at now."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    display_name: str
    symbol: str | None
    venues: list[Venue]


class InstrumentNotFound(BaseModel):
    reason: Literal["instrument_not_found"]


class InstrumentNotFoundResponse(BaseModel):
    detail: InstrumentNotFound
