"""The recent runs of the flows with their reports, and the stretches of the history no daily file
was asked for."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.data_status import LAST_DAY_RUN, PRICE_SOURCES
from api.services.flow_run_progress import stage_of
from api.services.market_reads import read_marts

RECENT_RUNS = 10

# A run started by a request names the admin who asked; one started otherwise names no one.
RUNS = text(
    "select run.run_id, run.flow, run.first_day, run.last_day, run.started_at, run.ended_at,"
    " run.outcome, run.counts, run.checks_passed, run.failures, run.warned_checks,"
    " run.failed_checks, run.failed_steps, run.unmaterialized,"
    " round(extract(epoch from run.ended_at - run.started_at))::integer as duration_seconds,"
    " person.display_name as requested_by"
    " from flow_run as run"
    " left join flow_request as request on request.id = run.request_id"
    " left join app_user as person on person.id = request.requested_by"
    " order by run.started_at desc limit :limit"
)
PUBLISHED_INSTRUMENTS = text(
    "select count(*) from mart_daily_features where trade_date = ("
    " select trade_date from feature_release order by release_id desc limit 1)"
)
# Consecutive days never asked for share their distance from their rank, which groups a stretch.
NEVER_ASKED_STRETCHES = text(
    "with missing as ("
    " select day::date as day from generate_series("
    " (select min(first_day) from mart_sources where source_id = any(:prices)),"
    " cast(:last_day as date), interval '1 day') as day"
    " where not exists (select from mart_source_days where trade_date = day::date))"
    " select min(day) as first_day, max(day) as last_day from ("
    " select day, day - cast(row_number() over (order by day) as integer) as stretch"
    " from missing) as grouped group by stretch order by first_day"
)


@dataclass(frozen=True)
class RecordedRun:
    """A finished run with its report as recorded."""

    run_id: str
    flow: str
    first_day: date
    last_day: date
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    outcome: str
    counts: dict[str, dict[str, int]]
    checks_passed: int
    failures: list[dict[str, Any]]
    warned_checks: list[dict[str, Any]]
    failed_checks: list[dict[str, Any]]
    failed_steps: list[str]
    unmaterialized: list[str]
    requested_by: str | None
    failed_stages: list[str]


@dataclass(frozen=True)
class DayStretch:
    first_day: date
    last_day: date


@dataclass(frozen=True)
class RunHistory:
    runs: tuple[RecordedRun, ...]
    days_never_asked: tuple[DayStretch, ...]
    published_instruments: int


async def run_history(database: Database, admin_id: int) -> RunHistory:
    return await read_marts(database, resolve_run_history, admin_id)


async def resolve_run_history(transaction: AsyncSession) -> RunHistory:
    runs = tuple(
        RecordedRun(
            **row._asdict(),
            failed_stages=sorted({stage_of(step) for step in row.failed_steps}),
        )
        for row in await transaction.execute(RUNS, {"limit": RECENT_RUNS})
    )
    last_day = (await transaction.execute(LAST_DAY_RUN)).scalar_one_or_none()
    stretches: tuple[DayStretch, ...] = ()
    if last_day is not None:
        found = await transaction.execute(
            NEVER_ASKED_STRETCHES, {"last_day": last_day, "prices": PRICE_SOURCES}
        )
        stretches = tuple(DayStretch(row.first_day, row.last_day) for row in found)
    published = (await transaction.execute(PUBLISHED_INSTRUMENTS)).scalar_one()
    return RunHistory(runs, stretches, published)
