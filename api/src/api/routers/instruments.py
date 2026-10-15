"""What the application knows each instrument by, for people signed in."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.dependencies import DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.instruments import InstrumentNotFoundResponse, InstrumentResponse
from api.services import instruments

# Two letters for the issuing country, nine characters naming the security, a check digit.
ISIN_PATTERN = "^[A-Z]{2}[A-Z0-9]{9}[0-9]$"

router = APIRouter(
    prefix="/instruments",
    tags=["instruments"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)


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
