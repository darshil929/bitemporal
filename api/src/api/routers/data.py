"""How current the shared market data is, for people signed in, and estimates of the flows for
admins."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import AdminDependency, DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.data_status import DataStatusResponse
from api.schemas.flow_run_estimates import RangeRefusedResponse, SyncEstimateResponse
from api.schemas.flow_run_history import RunHistoryResponse
from api.services import data_status as data_statuses
from api.services import flow_run_estimates, flow_run_history

router = APIRouter(
    prefix="/data",
    tags=["data"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)

RANGE_REFUSED: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": RangeRefusedResponse}
}


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


@router.get("/sync/estimate", responses=RANGE_REFUSED)
async def sync_estimate(
    first_day: date, last_day: date, _admin: AdminDependency, database: DatabaseDependency
) -> SyncEstimateResponse:
    """For admins, the days a sync over the range would ask each daily file for and how long it
    would take."""
    try:
        estimate = await flow_run_estimates.sync_estimate(database, first_day, last_day)
    except flow_run_estimates.RangeRefused as refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"reason": refused.reason}
        ) from refused
    return SyncEstimateResponse.model_validate(estimate)
