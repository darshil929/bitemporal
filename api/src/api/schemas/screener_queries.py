"""Bodies of the screener reads."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.market import Venue


class ScreenedRowResponse(BaseModel):
    """An instrument passing the screen: its name and symbol, the venue its figures were computed
    on, the close as traded and the day's return there, the spread between the venues, and the
    figures the screen gates and sorts on."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    display_name: str
    symbol: str | None
    primary_venue: Venue | None
    close: float | None
    return_1d: float | None
    venue_spread_bps: float | None
    is_diverging: bool | None
    figures: dict[str, float | None]


class ScreenerResponse(BaseModel):
    """A page of the instruments passing a screen on the latest day complete at every venue in
    session, absent before the first publish, and how many pass it in all; the pages stop at the
    row cap."""

    model_config = ConfigDict(from_attributes=True)

    day: date | None
    matched: int
    page: int
    page_size: int
    row_cap: int
    rows: list[ScreenedRowResponse]


class ScreenRefused(BaseModel):
    reason: Literal[
        "malformed_criterion",
        "unknown_figure",
        "unknown_comparison",
        "malformed_value",
        "malformed_gate",
        "unknown_sort",
    ]
    part: str


class ScreenRefusedResponse(BaseModel):
    detail: ScreenRefused
