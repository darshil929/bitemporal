"""Bodies of the key figure reads."""

from datetime import date

from pydantic import BaseModel, ConfigDict

from api.schemas.market import Venue


class SourceResponse(BaseModel):
    """A source figures are read from, with its trust tier and the SEBI curation row naming it."""

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    tier: int
    sebi_curation_ref: str | None


class KeyFiguresResponse(BaseModel):
    """The instrument's newest day at the venue up to the published day: the day as traded, its
    change and return on the adjusted series, its delivery share, the spread to the other venue and
    whether it diverged, the venue's verdict on the day, whether the day is older than the published
    one, and the sources read. Every figure is absent where the instrument never traded there."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    venue: Venue
    trade_date: date | None
    is_stale: bool | None
    is_day_complete: bool | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    previous_close: float | None
    volume: int | None
    turnover: float | None
    trade_count: int | None
    change_1d: float | None
    return_1d: float | None
    delivery_pct_1d: float | None
    venue_spread_bps: float | None
    is_diverging: bool | None
    sources: list[SourceResponse]
