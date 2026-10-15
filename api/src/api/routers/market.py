"""Reads of the shared market data, for people signed in."""

from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from api.dependencies import DatabaseDependency, signed_in
from api.schemas.market import MarketDataUpdatingResponse, MarketDayResponse
from api.schemas.sessions import NotSignedInResponse
from api.services import trading_days

# A sync builds a mart it dropped again moments later.
RETRY_AFTER_SECONDS = 5

MARKET_READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"model": NotSignedInResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": MarketDataUpdatingResponse},
}

router = APIRouter(
    prefix="/market",
    tags=["market"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)


async def market_data_updating(request: Request, error: Exception) -> JSONResponse:
    """The answer to a read whose mart stayed absent through the wait for a sync's rebuild."""
    return JSONResponse(
        {"detail": {"reason": "market_data_updating"}},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )


@router.get("/day")
async def market_day(database: DatabaseDependency) -> MarketDayResponse:
    """The day the market pages show, each venue's verdict on it, and the latest day up to it
    complete at every venue in session."""
    return MarketDayResponse.model_validate(await trading_days.market_day(database))
