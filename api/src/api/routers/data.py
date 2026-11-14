"""How current the shared market data is, for people signed in; estimates of the flows, and
requests for them, for admins."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import AdminDependency, DatabaseDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.data_status import DataStatusResponse
from api.schemas.flow_requests import (
    FlowRequestResponse,
    RequestEndedResponse,
    RequestPendingResponse,
    SyncRequestBody,
)
from api.schemas.flow_run_estimates import (
    BootstrapEstimateResponse,
    RangeRefusedResponse,
    SyncEstimateResponse,
)
from api.schemas.flow_run_history import RunHistoryResponse
from api.schemas.flow_run_progress import ProgressResponse
from api.services import data_status as data_statuses
from api.services import flow_requests, flow_run_estimates, flow_run_history, flow_run_progress

router = APIRouter(
    prefix="/data",
    tags=["data"],
    dependencies=[Depends(signed_in)],
    responses=MARKET_READ_RESPONSES,
)

RANGE_REFUSED: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": RangeRefusedResponse}
}
REQUEST_PENDING: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": RequestPendingResponse}
}
NOT_FOUND: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {}}


def pending_refusal(pending: flow_requests.RequestPending) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"reason": "request_pending", "request_id": pending.request_id},
    )


@router.get("/status")
async def data_status(database: DatabaseDependency) -> DataStatusResponse:
    """The day the pages show, each venue's latest day, the last run and the state they make; days
    of the history no daily file was asked for, counted to the latest day a run covered."""
    return DataStatusResponse.model_validate(await data_statuses.data_status(database))


@router.get("/runs")
async def run_history(admin: AdminDependency, database: DatabaseDependency) -> RunHistoryResponse:
    """For admins, the newest runs with their reports and the stretches of the history no daily
    file was asked for."""
    return RunHistoryResponse.model_validate(await flow_run_history.run_history(database, admin.id))


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


@router.get("/bootstrap/estimate")
async def bootstrap_estimate(
    _admin: AdminDependency, database: DatabaseDependency
) -> BootstrapEstimateResponse:
    """For admins, the history bootstrap's two runs, the days each would ask for and how long it
    would take."""
    return BootstrapEstimateResponse.model_validate(
        await flow_run_estimates.bootstrap_estimate(database)
    )


@router.post(
    "/sync", status_code=status.HTTP_202_ACCEPTED, responses=RANGE_REFUSED | REQUEST_PENDING
)
async def request_sync(
    body: SyncRequestBody, admin: AdminDependency, database: DatabaseDependency
) -> FlowRequestResponse:
    """For admins, ask for a sync over the range; the flows take it up within about 30 seconds."""
    try:
        added = await flow_requests.request_sync(database, admin.id, body.first_day, body.last_day)
    except flow_run_estimates.RangeRefused as refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"reason": refused.reason}
        ) from refused
    except flow_requests.RequestPending as pending:
        raise pending_refusal(pending) from pending
    return FlowRequestResponse.model_validate(added)


@router.post("/bootstrap", status_code=status.HTTP_202_ACCEPTED, responses=REQUEST_PENDING)
async def request_bootstrap(
    admin: AdminDependency, database: DatabaseDependency
) -> FlowRequestResponse:
    """For admins, ask for the history bootstrap: the two most recent years, then the rest."""
    try:
        added = await flow_requests.request_bootstrap(database, admin.id)
    except flow_requests.RequestPending as pending:
        raise pending_refusal(pending) from pending
    return FlowRequestResponse.model_validate(added)


@router.get("/requests/{request_id}", responses=NOT_FOUND)
async def flow_request(
    request_id: int, admin: AdminDependency, database: DatabaseDependency
) -> FlowRequestResponse:
    """For admins, a request as it stands."""
    found = await flow_requests.flow_request(database, admin.id, request_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    return FlowRequestResponse.model_validate(found)


@router.get("/requests/{request_id}/progress", responses=NOT_FOUND)
async def run_progress(
    request_id: int, _admin: AdminDependency, database: DatabaseDependency
) -> ProgressResponse:
    """For admins, a request's run as it goes: its status, its stages and the time left."""
    found = await flow_run_progress.run_progress(database, request_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    return ProgressResponse.model_validate(found)


@router.post(
    "/requests/{request_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    responses=NOT_FOUND | {status.HTTP_409_CONFLICT: {"model": RequestEndedResponse}},
)
async def cancel_request(
    request_id: int, admin: AdminDependency, database: DatabaseDependency
) -> FlowRequestResponse:
    """For admins, ask for a waiting or running request to be cancelled; the days a run stored
    stay."""
    try:
        cancelled = await flow_requests.cancel_request(database, admin.id, request_id)
    except flow_requests.RequestNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found"
        ) from missing
    except flow_requests.RequestEnded as ended:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "request_ended", "status": ended.status},
        ) from ended
    return FlowRequestResponse.model_validate(cancelled)
