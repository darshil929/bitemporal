"""Bodies of the screener reads."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.market import Venue


class UnhandledActionResponse(BaseModel):
    """A corporate action the adjusted prices do not account for, and the venue's text for it."""

    ex_date: date
    purpose: str


class ScreenedRowResponse(BaseModel):
    """An instrument passing the screen: its name and symbol, the venue its figures were computed
    on, the close as traded and the day's return there, the spread between the venues, and each
    figure the screen names. Whether it trades below the liquidity gate, unknown before twenty days
    of trading; the adjusted closes of its last 64 bars on that venue, oldest first, absent before
    64; and the unhandled corporate actions after the earliest bar those closes or its figures
    read, newest first."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    display_name: str
    symbol: str | None
    primary_venue: Venue | None
    close: float | None
    return_1d: float | None
    venue_spread_bps: float | None
    is_diverging: bool | None
    figures: dict[str, float | bool | None]
    is_below_gate: bool | None
    trend_3m: list[float] | None
    unhandled_actions: list[UnhandledActionResponse]


class StrictestCriterionResponse(BaseModel):
    """The criterion that alone excludes the most instruments of a screen nothing passes, as the
    address writes it, the gate only where no other criterion excludes any on its own: how many pass
    every other criterion, of how many the day holds of the screen's kind."""

    criterion: str
    is_gate: bool
    passing_the_rest: int
    screened: int


class ScreenerResponse(BaseModel):
    """A page of the instruments passing a screen on the latest day complete at every venue in
    session, absent before the first publish, and how many pass it in all; the pages stop at the
    row cap. Where nothing passes, the strictest criterion, absent where removing any one admits
    nothing."""

    model_config = ConfigDict(from_attributes=True)

    day: date | None
    matched: int
    page: int
    page_size: int
    row_cap: int
    rows: list[ScreenedRowResponse]
    strictest: StrictestCriterionResponse | None


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


class ScreenerUnavailable(BaseModel):
    reason: Literal["market_data_updating", "screener_query_timed_out"]


class ScreenerUnavailableResponse(BaseModel):
    detail: ScreenerUnavailable
