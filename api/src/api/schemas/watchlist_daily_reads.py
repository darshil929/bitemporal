"""Bodies of a watchlist's rows as the page shows them."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.key_figures import SourceResponse
from api.schemas.watchlist_management import AlertResponse


class VerdictResponse(BaseModel):
    """The alert's verdict on the latest session judged, with the figure its rule compared."""

    model_config = ConfigDict(from_attributes=True)

    trade_date: date
    status: Literal["triggered", "watching", "paused"]
    figure: float | None
    paused_reason: Literal["not_traded", "capital_action"] | None


class WatchlistRowResponse(BaseModel):
    """An entry on its venue's newest session up to the published day. Returns are fractions of
    the previous close on adjusted prices, delivery a percent of the volume, the spread basis points
    between the venues' closes; `is_stale` where the venue held a later session, `superseded_by` the
    ISIN that took a replaced one over, `verdict` null until the alert is first judged."""

    model_config = ConfigDict(from_attributes=True)

    entry_id: int
    isin: str
    venue: str
    display_name: str | None
    local_symbol: str | None
    primary_venue: str | None
    superseded_by: str | None
    trade_date: date | None
    is_stale: bool | None
    close: float | None
    change_1d: float | None
    return_1d: float | None
    return_1m: float | None
    delivery_pct_1d: float | None
    venue_spread_bps: float | None
    is_diverging: bool | None
    # The newest 22 adjusted closes up to the row's session, oldest first; null with fewer.
    trend_1m: list[float] | None
    alert: AlertResponse | None
    verdict: VerdictResponse | None


class WatchlistRowsResponse(BaseModel):
    """A list's entries in the order added, the day the daily features were published, how many
    alerts the latest sessions triggered, and the sources the figures shown are read from."""

    watchlist_id: int
    name: str
    is_default: bool
    published_day: date | None
    triggered: int
    rows: list[WatchlistRowResponse]
    sources: list[SourceResponse]
