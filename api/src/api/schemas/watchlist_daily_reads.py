"""Bodies of a watchlist's rows as the page shows them."""

from datetime import date

from pydantic import BaseModel, ConfigDict

from api.schemas.watchlist_management import AlertResponse


class WatchlistRowResponse(BaseModel):
    """An entry on its venue's newest session up to the published day. Returns are fractions of
    the previous close on adjusted prices, delivery a percent of the volume, the spread basis points
    between the venues' closes; `is_stale` where the venue held a later session, `superseded_by` the
    ISIN that took a replaced one over."""

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
    alert: AlertResponse | None


class WatchlistRowsResponse(BaseModel):
    """A list's entries in the order added and the day the daily features were published."""

    watchlist_id: int
    name: str
    is_default: bool
    published_day: date | None
    rows: list[WatchlistRowResponse]
