"""What the application knows each instrument by, for people signed in."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.dependencies import DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.corporate_actions import CorporateActionResponse
from api.schemas.instruments import (
    InstrumentMatchResponse,
    InstrumentNotFoundResponse,
    InstrumentResponse,
)
from api.schemas.key_figures import KeyFiguresResponse
from api.schemas.market import Venue
from api.schemas.price_history import PriceHistoryResponse, PriceRange
from api.services import (
    corporate_actions,
    instrument_identity,
    instrument_search,
    key_figures,
    price_history,
)

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

IsinPath = Annotated[str, Path(pattern=ISIN_PATTERN)]
NOT_FOUND_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": InstrumentNotFoundResponse}
}


def instrument_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail={"reason": "instrument_not_found"}
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


@router.get("/{isin}", responses=NOT_FOUND_RESPONSES)
async def instrument(isin: IsinPath, database: DatabaseDependency) -> InstrumentResponse:
    found = await instrument_identity.instrument(database, isin)
    if found is None:
        raise instrument_not_found()
    return InstrumentResponse.model_validate(found)


@router.get("/{isin}/prices", responses=NOT_FOUND_RESPONSES)
async def instrument_prices(
    isin: IsinPath,
    venue: Venue,
    database: DatabaseDependency,
    period: Annotated[PriceRange, Query(alias="range")] = "6M",
) -> PriceHistoryResponse:
    """The instrument's daily series at the venue over the range, as its price chart draws it."""
    found = await price_history.price_history(database, isin, venue, period)
    if found is None:
        raise instrument_not_found()
    return PriceHistoryResponse.model_validate(found)


@router.get("/{isin}/day", responses=NOT_FOUND_RESPONSES)
async def instrument_day(
    isin: IsinPath, venue: Venue, database: DatabaseDependency
) -> KeyFiguresResponse:
    """The instrument's newest day at the venue, as its key figures show it."""
    found = await key_figures.key_figures(database, isin, venue)
    if found is None:
        raise instrument_not_found()
    return KeyFiguresResponse.model_validate(found)


@router.get("/{isin}/actions", responses=NOT_FOUND_RESPONSES)
async def instrument_actions(
    isin: IsinPath, database: DatabaseDependency
) -> list[CorporateActionResponse]:
    """The instrument's corporate actions up to the published day, newest first."""
    found = await corporate_actions.corporate_actions(database, isin)
    if found is None:
        raise instrument_not_found()
    return [CorporateActionResponse.model_validate(action) for action in found]
