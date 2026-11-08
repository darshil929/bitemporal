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


class SupersededEntryResponse(BaseModel):
    """An entry whose ISIN a change of face value replaced, and the ISIN that took it over."""

    model_config = ConfigDict(from_attributes=True)

    entry_id: int
    watchlist_id: int
    isin: str
    display_name: str | None
    superseded_by: str


class AttentionResponse(BaseModel):
    """What needs the person's attention on the published day; every list empty when nothing does."""

    model_config = ConfigDict(from_attributes=True)

    published_day: date | None
    alerts: list[TriggeredAlertResponse]
    superseded: list[SupersededEntryResponse]
