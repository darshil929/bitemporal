"""An admin's requests for a sync or the history bootstrap, which the flows pick up from Postgres.

A request is written with an audit event in one transaction. While one request waits or runs no
other is taken, so two admins asking at once cannot both start a flow.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services import data_status
from api.services.audit import record_admin_action
from api.services.flow_run_estimates import check_range, first_day

# Held to the end of the transaction, so requests are checked and added one at a time.
REQUESTS_LOCK = text("select pg_advisory_xact_lock(hashtext('flow_request'))")
PENDING = text(
    "select id from flow_request where status in ('requested', 'started') order by id limit 1"
)
ADD = text(
    "insert into flow_request (flow, first_day, last_day, requested_by)"
    " values (:flow, :first, :last, :person) returning id"
)
REQUEST = text(
    "select request.id, request.flow, request.first_day, request.last_day, request.status,"
    " person.display_name as requested_by, request.requested_at, request.started_at,"
    " request.finished_at, request.refusal"
    " from flow_request as request left join app_user as person on person.id = request.requested_by"
    " where request.id = :id"
)
RUNS = text(
    "select run_id, first_day, last_day, outcome from flow_run where request_id = :id"
    " order by started_at"
)


class RequestPending(Exception):
    """Another request waits or runs."""

    def __init__(self, request_id: int) -> None:
        super().__init__(request_id)
        self.request_id = request_id


@dataclass(frozen=True)
class RequestRun:
    run_id: str
    first_day: date
    last_day: date
    outcome: str


@dataclass(frozen=True)
class FlowRequest:
    """A request as it stands: refused with the reason and its facts, or started and the outcome of
    each run it took."""

    id: int
    flow: str
    first_day: date
    last_day: date
    status: str
    requested_by: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    refusal: dict[str, Any] | None
    runs: tuple[RequestRun, ...]


async def read_request(transaction: AsyncSession, request_id: int) -> FlowRequest | None:
    row = (await transaction.execute(REQUEST, {"id": request_id})).one_or_none()
    if row is None:
        return None
    runs = tuple(RequestRun(*run) for run in await transaction.execute(RUNS, {"id": request_id}))
    return FlowRequest(**row._asdict(), runs=runs)


async def add_request(
    transaction: AsyncSession, admin_id: int, flow: str, first: date, last: date
) -> FlowRequest:
    await transaction.execute(REQUESTS_LOCK)
    pending = (await transaction.execute(PENDING)).scalar_one_or_none()
    if pending is not None:
        raise RequestPending(pending)
    request_id = (
        await transaction.execute(
            ADD, {"flow": flow, "first": first, "last": last, "person": admin_id}
        )
    ).scalar_one()
    await record_admin_action(
        transaction,
        admin_id,
        "sync_started" if flow == "sync" else "bootstrap_started",
        detail={"request_id": request_id, "first_day": str(first), "last_day": str(last)},
    )
    added = await read_request(transaction, request_id)
    assert added is not None
    return added


async def request_sync(database: Database, admin_id: int, first: date, last: date) -> FlowRequest:
    async with database.transaction(admin_id) as transaction:
        await check_range(transaction, first, last)
        return await add_request(transaction, admin_id, "sync", first, last)


async def request_bootstrap(database: Database, admin_id: int) -> FlowRequest:
    """A bootstrap over the whole history, from the price files' first day to today in India."""
    today = data_status.india_now().date()
    async with database.transaction(admin_id) as transaction:
        first = await first_day(transaction) or today
        return await add_request(transaction, admin_id, "bootstrap", first, today)


async def flow_request(database: Database, admin_id: int, request_id: int) -> FlowRequest | None:
    async with database.transaction(admin_id) as transaction:
        return await read_request(transaction, request_id)
