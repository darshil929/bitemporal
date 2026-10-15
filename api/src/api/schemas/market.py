"""Bodies of the market reads."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Venue = Literal["BSE", "NSE"]


class VenueSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    venue: Venue
    is_complete: bool


class MarketDayResponse(BaseModel):
    """The day the market pages show; every field absent before the first publish of the daily
    features."""

    model_config = ConfigDict(from_attributes=True)

    published_day: date | None
    published_at: datetime | None
    venues: list[VenueSessionResponse]
    last_complete_day: date | None


class MarketDataUpdating(BaseModel):
    reason: Literal["market_data_updating"]


class MarketDataUpdatingResponse(BaseModel):
    detail: MarketDataUpdating
