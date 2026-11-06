"""Screens of the daily features, for people signed in."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from api.dependencies import DatabaseDependency, SignedInDependency, signed_in
from api.schemas.saved_screener_views import (
    SavedViewChangeRequest,
    SavedViewRequest,
    SavedViewResponse,
    ViewRefusedResponse,
)
from api.schemas.screener_queries import (
    ScreenedRowResponse,
    ScreenerResponse,
    ScreenerUnavailableResponse,
    ScreenRefusedResponse,
    StrictestCriterionResponse,
)
from api.schemas.sessions import NotSignedInResponse
from api.services import saved_screener_views, screener_queries
from api.services.saved_screener_views import ViewRefused
from api.services.screener_queries import PAGE_SIZE, PAGES, ROW_CAP, Kind, ScreenRefused

router = APIRouter(
    prefix="/screener",
    tags=["screener"],
    dependencies=[Depends(signed_in)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": NotSignedInResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ScreenerUnavailableResponse},
    },
)


Responses = dict[int | str, dict[str, Any]]
UNSCREENABLE: Responses = {status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ScreenRefusedResponse}}
NOT_FOUND: Responses = {status.HTTP_404_NOT_FOUND: {"model": ViewRefusedResponse}}
CONFLICT: Responses = {status.HTTP_409_CONFLICT: {"model": ViewRefusedResponse}}
# A view the person does not keep answers 404; a name the person keeps already, 409.
VIEW_REFUSED_AS = {
    "view_not_found": status.HTTP_404_NOT_FOUND,
    "view_name_taken": status.HTTP_409_CONFLICT,
}


def screen_refusal(refused: ScreenRefused) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"reason": refused.reason, "part": refused.part},
    )


def view_refusal(refused: ViewRefused) -> HTTPException:
    return HTTPException(
        status_code=VIEW_REFUSED_AS[refused.reason], detail={"reason": refused.reason}
    )


async def screen_timed_out(request: Request, error: Exception) -> JSONResponse:
    """The answer to a screen that ran past the time a query may take; no part of it is shown."""
    return JSONResponse(
        {"detail": {"reason": "screener_query_timed_out"}},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get("", responses=UNSCREENABLE)
async def screen(
    database: DatabaseDependency,
    gate: str | None = None,
    kind: Kind = "companies",
    c: Annotated[list[str] | None, Query()] = None,
    sort: str | None = None,
    page: Annotated[int, Query(ge=1, le=PAGES)] = 1,
) -> ScreenerResponse:
    """The instruments passing the liquidity gate, unless `none`, and every criterion `c`, written
    `figure:comparison:value`; companies alone unless `kind=all`; in the order of `sort`, written
    `figure:asc` or `figure:desc`, the most traded first by default; 50 a page up to 500."""
    try:
        asked = screener_queries.screen_from(gate, kind, c or [], sort, page)
    except ScreenRefused as refused:
        raise screen_refusal(refused) from refused
    found = await screener_queries.run_screen(database, asked)
    strictest = None
    if found.strictest is not None:
        strictest = StrictestCriterionResponse(
            criterion=found.strictest.criterion.part,
            is_gate=found.strictest.is_gate,
            passing_the_rest=found.strictest.passing_the_rest,
            screened=found.strictest.screened,
        )
    return ScreenerResponse(
        day=found.day,
        matched=found.matched,
        page=found.page,
        page_size=PAGE_SIZE,
        row_cap=ROW_CAP,
        rows=[ScreenedRowResponse.model_validate(row) for row in found.rows],
        strictest=strictest,
    )


@router.get("/views")
async def saved_views(
    user: SignedInDependency, database: DatabaseDependency
) -> list[SavedViewResponse]:
    """The person's saved views, by name whatever its case."""
    views = await saved_screener_views.saved_views(database, user.id)
    return [SavedViewResponse.model_validate(view) for view in views]


@router.post("/views", status_code=status.HTTP_201_CREATED, responses=CONFLICT | UNSCREENABLE)
async def save_view(
    body: SavedViewRequest, user: SignedInDependency, database: DatabaseDependency
) -> SavedViewResponse:
    """Keep a screen under a name; the screen kept is the one the screener would show."""
    try:
        saved = await saved_screener_views.save_view(database, user.id, body.name, body.query)
    except ScreenRefused as refused:
        raise screen_refusal(refused) from refused
    except ViewRefused as refused:
        raise view_refusal(refused) from refused
    return SavedViewResponse.model_validate(saved)


@router.patch("/views/{view_id}", responses=NOT_FOUND | CONFLICT | UNSCREENABLE)
async def change_view(
    view_id: int,
    body: SavedViewChangeRequest,
    user: SignedInDependency,
    database: DatabaseDependency,
) -> SavedViewResponse:
    """Rename a view, save another screen over it, or both."""
    try:
        changed = await saved_screener_views.change_view(
            database, user.id, view_id, body.name, body.query
        )
    except ScreenRefused as refused:
        raise screen_refusal(refused) from refused
    except ViewRefused as refused:
        raise view_refusal(refused) from refused
    return SavedViewResponse.model_validate(changed)


@router.delete("/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def remove_view(view_id: int, user: SignedInDependency, database: DatabaseDependency) -> None:
    """Take a view off the person's list, which frees its name."""
    try:
        await saved_screener_views.remove_view(database, user.id, view_id)
    except ViewRefused as refused:
        raise view_refusal(refused) from refused
