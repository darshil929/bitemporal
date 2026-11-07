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


class WatchlistResponse(BaseModel):
    """A list the person keeps; the default is the earliest of them."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class WatchlistRefused(BaseModel):
    reason: Literal["watchlist_name_taken", "watchlist_limit_reached", "watchlist_not_found"]


class WatchlistRefusedResponse(BaseModel):
    detail: WatchlistRefused
