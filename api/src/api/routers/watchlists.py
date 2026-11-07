"""A person's watchlists, for people signed in."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import DatabaseDependency, SignedInDependency, signed_in
from api.schemas.sessions import NotSignedInResponse
from api.schemas.watchlist_management import (
    WatchlistRefusedResponse,
    WatchlistRequest,
    WatchlistResponse,
)
from api.services import watchlist_management
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
OVER_LIMIT: Responses = {status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": WatchlistRefusedResponse}}
# A list the person does not keep answers 404; a name the person keeps already, 409; a list past
# the limit, 422.
REFUSED_AS = {
    "watchlist_not_found": status.HTTP_404_NOT_FOUND,
    "watchlist_name_taken": status.HTTP_409_CONFLICT,
    "watchlist_limit_reached": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def refusal(refused: WatchlistRefused) -> HTTPException:
    return HTTPException(status_code=REFUSED_AS[refused.reason], detail={"reason": refused.reason})


@router.get("")
async def watchlists(
    user: SignedInDependency, database: DatabaseDependency
) -> list[WatchlistResponse]:
    """The person's lists, the default first, then by name whatever its case."""
    kept = await watchlist_management.watchlists(database, user.id)
    return [WatchlistResponse.model_validate(watchlist) for watchlist in kept]


@router.post("", status_code=status.HTTP_201_CREATED, responses=CONFLICT | OVER_LIMIT)
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
    """Take a list off the person's lists, which frees its name."""
    try:
        await watchlist_management.remove_watchlist(database, user.id, watchlist_id)
    except WatchlistRefused as refused:
        raise refusal(refused) from refused
