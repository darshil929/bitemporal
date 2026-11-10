"""How current the shared market data is, for people signed in."""

from fastapi import APIRouter, Depends

from api.dependencies import DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.data_status import DataStatusResponse
from api.services import data_status as data_statuses

router = APIRouter(
    prefix="/data",
    tags=["data"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)


@router.get("/status")
async def data_status(database: DatabaseDependency) -> DataStatusResponse:
    """The day the pages show, each venue's latest day, the last run and the state they make."""
    return DataStatusResponse.model_validate(await data_statuses.data_status(database))
