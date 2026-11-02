"""Bodies of the market summary read."""

from datetime import date

from pydantic import BaseModel, ConfigDict

from api.schemas.key_figures import SourceResponse


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


class MarketSummaryResponse(BaseModel):
    """Breadth on the latest day complete at every venue in session, with the sources behind it;
    absent before the first publish."""

    model_config = ConfigDict(from_attributes=True)

    day: date | None
    breadth: BreadthResponse | None
    breadth_sources: list[SourceResponse]
