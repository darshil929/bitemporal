"""Bodies of the market summary read."""

from datetime import date

from pydantic import BaseModel, ConfigDict

from api.schemas.key_figures import SourceResponse
from api.schemas.market import Venue
from api.schemas.screener_queries import UnhandledActionResponse


class BreadthResponse(BaseModel):
    """The companies that traded on the day, each on its primary venue: how many, how many rose, fell
    and stood unchanged, a company on its first bar counting in none of those, how many made a new
    52-week high or low, and the median day's return."""

    model_config = ConfigDict(from_attributes=True)

    companies: int
    advancing: int
    declining: int
    unchanged: int
    new_52w_highs: int
    new_52w_lows: int
    median_return_1d: float | None


class MoverResponse(BaseModel):
    """A company among those that moved most: its name and symbol, the venue its figures were computed
    on, the close as traded, the day's return, its volume against twenty days and its delivery share
    there, and any unhandled corporate action the day's return runs through."""

    model_config = ConfigDict(from_attributes=True)

    isin: str
    display_name: str
    symbol: str | None
    primary_venue: Venue
    close: float | None
    return_1d: float
    volume_ratio_20d: float | None
    delivery_pct_1d: float | None
    unhandled_actions: list[UnhandledActionResponse]


class BelowGateMoveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    isin: str
    display_name: str
    return_1d: float


class MovedMostResponse(BaseModel):
    """The companies that moved most one way past the liquidity gate, largest first. Of those below
    the gate that moved further than the last of them: the largest moves, and how many more."""

    model_config = ConfigDict(from_attributes=True)

    rows: list[MoverResponse]
    below_gate: list[BelowGateMoveResponse]
    more_below_gate: int


class MarketSummaryResponse(BaseModel):
    """Breadth and the companies that moved most on the latest day complete at every venue in
    session, each with the sources behind it; absent before the first publish."""

    model_config = ConfigDict(from_attributes=True)

    day: date | None
    breadth: BreadthResponse | None
    moved_up: MovedMostResponse
    moved_down: MovedMostResponse
    breadth_sources: list[SourceResponse]
    mover_sources: list[SourceResponse]
