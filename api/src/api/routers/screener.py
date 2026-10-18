"""Screens of the daily features, for people signed in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.dependencies import DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.screener_queries import (
    ScreenedRowResponse,
    ScreenerResponse,
    ScreenRefusedResponse,
)
from api.services import screener_queries
from api.services.screener_queries import PAGE_SIZE, PAGES, ROW_CAP, Kind, ScreenRefused

router = APIRouter(
    prefix="/screener",
    tags=["screener"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)


@router.get("", responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ScreenRefusedResponse}})
async def screen(
    database: DatabaseDependency,
    gate: str | None = None,
    kind: Kind = "companies",
    sort: str | None = None,
    page: Annotated[int, Query(ge=1, le=PAGES)] = 1,
) -> ScreenerResponse:
    """The instruments passing the liquidity gate, written `adtv_20d:comparison:value` or `none`;
    companies alone unless `kind=all`; in the order of `sort`, written `figure:asc` or
    `figure:desc`, the most traded first by default; 50 a page up to 500."""
    try:
        asked = screener_queries.screen_from(gate, kind, sort, page)
    except ScreenRefused as refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"reason": refused.reason, "part": refused.part},
        ) from refused
    found = await screener_queries.run_screen(database, asked)
    return ScreenerResponse(
        day=found.day,
        matched=found.matched,
        page=found.page,
        page_size=PAGE_SIZE,
        row_cap=ROW_CAP,
        rows=[ScreenedRowResponse.model_validate(row) for row in found.rows],
    )
