"""Bodies of the watchlist reads and changes."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

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


class EntryResponse(BaseModel):
    """An instrument a list follows on one venue, since it was added there."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    watchlist_id: int
    isin: str
    venue: str
    added_at: datetime


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
        "entry_limit_reached",
        "instrument_already_listed",
        "instrument_not_listed",
        "venue_not_listed",
    ]


class WatchlistRefusedResponse(BaseModel):
    detail: WatchlistRefused
