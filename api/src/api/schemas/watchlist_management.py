"""Bodies of the watchlist reads and changes."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

WatchlistName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class WatchlistRequest(BaseModel):
    """A name to keep a list under, or to rename it to."""

    name: WatchlistName


Isin = Annotated[str, StringConstraints(pattern="^[A-Z]{2}[A-Z0-9]{9}[0-9]$")]
Venue = Annotated[str, StringConstraints(pattern="^[A-Z][A-Z0-9]{1,11}$")]


class EntryRequest(BaseModel):
    """An instrument to follow, on the venue named or else its primary venue, in the list named or
    else the default, which a person keeping no list gains under the name Watchlist."""

    isin: Isin
    venue: Venue | None = None
    watchlist_id: int | None = None


class EntryVenueRequest(BaseModel):
    """The venue an entry follows from now."""

    venue: Venue


AlertRule = Literal[
    "move_beyond", "close_above", "close_below", "delivery_above", "delivery_below", "spread_above"
]
# The largest figure a stored threshold holds.
LARGEST_THRESHOLD = 999_999_999_999


class AlertRequest(BaseModel):
    """The rule an entry's alert evaluates, in the unit the daily figures hold: a move beyond plus or
    minus a fraction (0.02 for 2%), a close above or below a price in rupees, delivery above or below
    a percent, the spread above a number of basis points."""

    rule: AlertRule
    threshold: Annotated[float, Field(gt=0, le=LARGEST_THRESHOLD)]

    @model_validator(mode="after")
    def delivery_below_whole(self) -> Self:
        if self.rule.startswith("delivery") and self.threshold >= 100:
            raise ValueError("a delivery threshold is a percent below 100")
        return self


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule: AlertRule
    threshold: float
    created_at: datetime


class EntryResponse(BaseModel):
    """An instrument a list follows on one venue, since it was added there."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    watchlist_id: int
    isin: str
    venue: str
    added_at: datetime
    alert: AlertResponse | None


class WatchlistResponse(BaseModel):
    """A list the person keeps; the default is the earliest of them."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
    entries: list[EntryResponse]


class WatchlistRefused(BaseModel):
    reason: Literal[
        "watchlist_name_taken",
        "watchlist_limit_reached",
        "watchlist_not_found",
        "entry_not_found",
        "alert_not_found",
        "entry_limit_reached",
        "instrument_already_listed",
        "instrument_not_listed",
        "venue_not_listed",
    ]


class WatchlistRefusedResponse(BaseModel):
    detail: WatchlistRefused
