"""Bodies of the needs-attention feed."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class TriggeredAlertResponse(BaseModel):
    """An alert the newest session at its venue triggered, with the figure its rule compared."""

    model_config = ConfigDict(from_attributes=True)

    entry_id: int
    watchlist_id: int
    isin: str
    display_name: str | None
    venue: str
    rule: str
    threshold: float
    trade_date: date
    figure: float | None


class IncompleteSessionResponse(BaseModel):
    """A venue's session on the published day that failed its checks, and why."""

    model_config = ConfigDict(from_attributes=True)

    venue: str
    trade_date: date
    divergent_instruments: int
    detail: str | None


class DivergenceResponse(BaseModel):
    """A held instrument whose venues' closes diverge on the published day, in basis points."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    display_name: str | None
    venue_spread_bps: float | None


class SupersededEntryResponse(BaseModel):
    """An entry whose ISIN a change of face value replaced, and the ISIN that took it over."""

    model_config = ConfigDict(from_attributes=True)

    entry_id: int
    watchlist_id: int
    isin: str
    display_name: str | None
    superseded_by: str


class UnhandledActionResponse(BaseModel):
    """A corporate action no factor adjusts on a held instrument, within the sessions a month's
    return reads."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    display_name: str | None
    ex_date: date
    purpose: str | None


class AttentionResponse(BaseModel):
    """What needs the person's attention on the published day; every list empty when nothing does."""

    model_config = ConfigDict(from_attributes=True)

    published_day: date | None
    alerts: list[TriggeredAlertResponse]
    incomplete_sessions: list[IncompleteSessionResponse]
    divergences: list[DivergenceResponse]
    superseded: list[SupersededEntryResponse]
    unhandled_actions: list[UnhandledActionResponse]
