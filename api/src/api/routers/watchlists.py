"""A person's watchlists, for people signed in."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import DatabaseDependency, SignedInDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.key_figures import SourceResponse
from api.schemas.sessions import NotSignedInResponse
from api.schemas.watchlist_daily_reads import WatchlistRowResponse, WatchlistRowsResponse
from api.schemas.watchlist_management import (
    AlertRequest,
    AlertResponse,
    EntryRequest,
    EntryResponse,
    EntryVenueRequest,
    WatchlistRefusedResponse,
    WatchlistRequest,
    WatchlistResponse,
)
from api.services import watchlist_daily_reads, watchlist_management
from api.services.watchlist_management import WatchlistRefused

router = APIRouter(
    prefix="/watchlists",
    tags=["watchlists"],
    dependencies=[Depends(signed_in)],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": NotSignedInResponse}},
)

Responses = dict[int | str, dict[str, Any]]
NOT_FOUND: Responses = {status.HTTP_404_NOT_FOUND: {"model": WatchlistRefusedResponse}}
CONFLICT: Responses = {status.HTTP_409_CONFLICT: {"model": WatchlistRefusedResponse}}
UNADMITTED: Responses = {status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": WatchlistRefusedResponse}}
# A list, entry or alert the person does not keep answers 404; a name or instrument the list keeps already,
# 409; a change past a limit or onto a venue the instrument is not listed on, 422.
REFUSED_AS = {
    "watchlist_not_found": status.HTTP_404_NOT_FOUND,
    "entry_not_found": status.HTTP_404_NOT_FOUND,
    "alert_not_found": status.HTTP_404_NOT_FOUND,
    "watchlist_name_taken": status.HTTP_409_CONFLICT,
    "instrument_already_listed": status.HTTP_409_CONFLICT,
    "watchlist_limit_reached": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "entry_limit_reached": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "instrument_not_listed": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "venue_not_listed": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def refusal(refused: WatchlistRefused) -> HTTPException:
    return HTTPException(status_code=REFUSED_AS[refused.reason], detail={"reason": refused.reason})


@router.get("")
async def watchlists(
    user: SignedInDependency, database: DatabaseDependency
) -> list[WatchlistResponse]:
    """The person's lists, the default first, then by name, each with its entries in added order."""
    kept = await watchlist_management.watchlists(database, user.id)
    return [WatchlistResponse.model_validate(watchlist) for watchlist in kept]


@router.post("", status_code=status.HTTP_201_CREATED, responses=CONFLICT | UNADMITTED)
async def add_watchlist(
    body: WatchlistRequest, user: SignedInDependency, database: DatabaseDependency
) -> WatchlistResponse:
    """Keep a new list under a name, up to twenty lists."""
    try:
        added = await watchlist_management.add_watchlist(database, user.id, body.name)
    except WatchlistRefused as refused:
        raise refusal(refused) from refused
    return WatchlistResponse.model_validate(added)


@router.patch("/{watchlist_id}", responses=NOT_FOUND | CONFLICT)
async def rename_watchlist(
    watchlist_id: int,
    body: WatchlistRequest,
    user: SignedInDependency,
    database: DatabaseDependency,
) -> WatchlistResponse:
    try:
        renamed = await watchlist_management.rename_watchlist(
            database, user.id, watchlist_id, body.name
        )
    except WatchlistRefused as refused:
        raise refusal(refused) from refused
    return WatchlistResponse.model_validate(renamed)


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def remove_watchlist(
    watchlist_id: int, user: SignedInDependency, database: DatabaseDependency
) -> None:
    """Take a list off the person's lists, which frees its name and ends every entry it holds."""
    try:
        await watchlist_management.remove_watchlist(database, user.id, watchlist_id)
    except WatchlistRefused as refused:
        raise refusal(refused) from refused


@router.post(
    "/entries",
    status_code=status.HTTP_201_CREATED,
    responses=NOT_FOUND | CONFLICT | UNADMITTED | MARKET_READ_RESPONSES,
)
async def add_entry(
    body: EntryRequest, user: SignedInDependency, database: DatabaseDependency
) -> EntryResponse:
    """Follow an instrument on a venue it is listed on now, up to 500 in a list."""
    try:
        added = await watchlist_management.add_entry(
            database, user.id, body.isin, body.venue, body.watchlist_id
        )
    except WatchlistRefused as refused:
        raise refusal(refused) from refused
    return EntryResponse.model_validate(added)


@router.patch("/entries/{entry_id}", responses=NOT_FOUND | UNADMITTED | MARKET_READ_RESPONSES)
async def change_entry_venue(
    entry_id: int,
    body: EntryVenueRequest,
    user: SignedInDependency,
    database: DatabaseDependency,
) -> EntryResponse:
    """Follow the entry's instrument on another venue from now: the entry ends and the one answered
    takes its place."""
    try:
        changed = await watchlist_management.change_entry_venue(
            database, user.id, entry_id, body.venue
        )
    except WatchlistRefused as refused:
        raise refusal(refused) from refused
    return EntryResponse.model_validate(changed)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def remove_entry(
    entry_id: int, user: SignedInDependency, database: DatabaseDependency
) -> None:
    """Stop following an instrument; the entry ends and its history stays."""
    try:
        await watchlist_management.remove_entry(database, user.id, entry_id)
    except WatchlistRefused as refused:
        raise refusal(refused) from refused


@router.put("/entries/{entry_id}/alert", responses=NOT_FOUND)
async def set_alert(
    entry_id: int, body: AlertRequest, user: SignedInDependency, database: DatabaseDependency
) -> AlertResponse:
    """Give an entry its alert, ending the one it held unless the rule is the same."""
    try:
        alert = await watchlist_management.set_alert(
            database, user.id, entry_id, body.rule, Decimal(str(body.threshold))
        )
    except WatchlistRefused as refused:
        raise refusal(refused) from refused
    return AlertResponse.model_validate(alert)


@router.delete(
    "/entries/{entry_id}/alert", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND
)
async def remove_alert(
    entry_id: int, user: SignedInDependency, database: DatabaseDependency
) -> None:
    """End an entry's alert; its rules stay in its history."""
    try:
        await watchlist_management.remove_alert(database, user.id, entry_id)
    except WatchlistRefused as refused:
        raise refusal(refused) from refused


@router.get("/{watchlist_id}/rows", responses=NOT_FOUND | MARKET_READ_RESPONSES)
async def watchlist_rows(
    watchlist_id: int, user: SignedInDependency, database: DatabaseDependency
) -> WatchlistRowsResponse:
    """A list's entries with each instrument's newest session at the entry's venue and the alert's
    latest verdict."""
    try:
        found = await watchlist_daily_reads.watchlist_rows(database, user.id, watchlist_id)
    except WatchlistRefused as refused:
        raise refusal(refused) from refused
    return WatchlistRowsResponse(
        watchlist_id=found.watchlist.id,
        name=found.watchlist.name,
        is_default=found.watchlist.is_default,
        published_day=found.published_day,
        triggered=found.triggered,
        rows=[WatchlistRowResponse.model_validate(row) for row in found.rows],
        sources=[SourceResponse.model_validate(source) for source in found.sources],
    )
