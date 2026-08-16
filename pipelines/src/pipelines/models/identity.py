"""Canonical rows describing what an instrument is and where it trades."""

from datetime import date

from pydantic import BaseModel


class InstrumentRecord(BaseModel):
    isin: str
    name: str
    country: str
    instrument_type: str


class ListingRecord(BaseModel):
    """One stretch during which an instrument traded under one symbol at one venue.

    A rename closes the current stretch and opens another rather than overwriting it, so the
    symbol in force on a past date stays recoverable.
    """

    isin: str
    exchange: str
    local_symbol: str
    scrip_code: str | None
    listing_date: date
    delisting_date: date | None
    closure_reason: str | None


class PrimaryVenueRecord(BaseModel):
    """The venue an instrument's series is computed from, over a span of dates."""

    isin: str
    effective_from: date
    as_of_date: date
    effective_to: date | None
    venue: str
