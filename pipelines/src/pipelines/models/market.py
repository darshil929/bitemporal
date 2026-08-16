"""Canonical rows produced by the source adapters."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PriceBar(BaseModel):
    """One instrument's trading for one day at one venue, keyed on ISIN.

    `as_of_date` equals `trade_date` because a venue publishes the day's bhavcopy the same
    evening. A correction republished later carries the date it was republished.
    """

    isin: str
    venue: str
    trade_date: date
    as_of_date: date
    local_symbol: str
    scrip_code: str | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal | None
    volume: int
    turnover: Decimal | None
    trade_count: int | None
