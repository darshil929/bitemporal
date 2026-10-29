"""Screens of the daily features, for people signed in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from api.dependencies import DatabaseDependency, signed_in
from api.schemas.screener_queries import (
    ScreenedRowResponse,
    ScreenerResponse,
    ScreenerUnavailableResponse,
    ScreenRefusedResponse,
    StrictestCriterionResponse,
)
from api.schemas.sessions import NotSignedInResponse
from api.services import screener_queries
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


async def screen_timed_out(request: Request, error: Exception) -> JSONResponse:
    """The answer to a screen that ran past the time a query may take; no part of it is shown."""
    return JSONResponse(
        {"detail": {"reason": "screener_query_timed_out"}},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get("", responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ScreenRefusedResponse}})
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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"reason": refused.reason, "part": refused.part},
        ) from refused
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
