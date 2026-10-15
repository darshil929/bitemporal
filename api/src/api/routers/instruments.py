"""What the application knows each instrument by, for people signed in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.dependencies import DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.instruments import (
    InstrumentMatchResponse,
    InstrumentNotFoundResponse,
    InstrumentResponse,
)
from api.services import instrument_search, instruments

# Two letters for the issuing country, nine characters naming the security, a check digit.
ISIN_PATTERN = "^[A-Z]{2}[A-Z0-9]{9}[0-9]$"
# At least two characters, with no space before or after them.
SEARCH_PATTERN = r"^\S.*\S$"
LONGEST_SEARCH = 64

router = APIRouter(
    prefix="/instruments",
    tags=["instruments"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)


@router.get("")
async def search_instruments(
    q: Annotated[str, Query(max_length=LONGEST_SEARCH, pattern=SEARCH_PATTERN)],
    database: DatabaseDependency,
) -> list[InstrumentMatchResponse]:
    """Up to ten instruments whose name holds the text, or whose symbol or ISIN starts with it, or
    whose scrip code is it; instruments listed now first."""
    found = await instrument_search.search_instruments(database, q)
    return [InstrumentMatchResponse.model_validate(match) for match in found]


@router.get("/{isin}", responses={status.HTTP_404_NOT_FOUND: {"model": InstrumentNotFoundResponse}})
async def instrument(
    isin: Annotated[str, Path(pattern=ISIN_PATTERN)], database: DatabaseDependency
) -> InstrumentResponse:
    found = await instruments.instrument(database, isin)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"reason": "instrument_not_found"}
        )
    return InstrumentResponse.model_validate(found)
