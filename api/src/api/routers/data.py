"""How current the shared market data is, for people signed in."""

from fastapi import APIRouter, Depends

from api.dependencies import AdminDependency, DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.data_status import DataStatusResponse
from api.schemas.flow_run_history import RunHistoryResponse
from api.services import data_status as data_statuses
from api.services import flow_run_history

router = APIRouter(
    prefix="/data",
    tags=["data"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)


@router.get("/status")
async def data_status(database: DatabaseDependency) -> DataStatusResponse:
    """The day the pages show, each venue's latest day, the last run and the state they make; days
    of the history no daily file was asked for, counted to the latest day a run covered."""
    return DataStatusResponse.model_validate(await data_statuses.data_status(database))


@router.get("/runs")
async def run_history(_admin: AdminDependency, database: DatabaseDependency) -> RunHistoryResponse:
    """For admins, the newest runs with their reports and the stretches of the history no daily
    file was asked for."""
    return RunHistoryResponse.model_validate(await flow_run_history.run_history(database))
