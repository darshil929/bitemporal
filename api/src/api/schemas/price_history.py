"""Bodies of the price history reads."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.market import Venue

PriceRange = Literal["1M", "3M", "6M", "1Y", "All"]


class PriceDayResponse(BaseModel):
    """A trading day at the venue: the candle, volume and delivery adjusted for every later action,
    the close as traded with the factor between the two, the other venue's adjusted close, the
    spread and whether it diverged, and the overlays in the candle's scale, absent on a day whose
    daily features were computed on the other venue."""

    model_config = ConfigDict(from_attributes=True)

    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    close_as_traded: float | None
    adjustment_factor: float
    volume: float
    delivery_quantity: float | None
    other_venue_close: float | None
    venue_spread_bps: float | None
    is_diverging: bool | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_20: float | None
    ema_50: float | None
    bollinger_20_upper: float | None
    bollinger_20_lower: float | None


class PriceHistoryResponse(BaseModel):
    """The days of the range at the venue, ending on the instrument's newest day there up to the
    published day, a replaced ISIN's own days alone; and the median spread over those days, absent
    where none has one."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    venue: Venue
    range: PriceRange
    first_day: date | None
    last_day: date | None
    days: list[PriceDayResponse]
    venue_spread_median_bps: float | None
