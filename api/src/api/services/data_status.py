"""How current the market data is: the day the pages show, each venue's latest day, the last run of
a flow, a sync running, and whether the data is fresh, stale, updating or failed."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts
from api.services.trading_days import PUBLISHED

if TYPE_CHECKING:
    from api.services.flow_run_estimates import Duration

INDIA = ZoneInfo("Asia/Kolkata")

# The morning sync runs at 07:30 India time, by when every file of the weekday before is due.
FILES_DUE = time(7, 30)

# A weekday both venues' price files answered not published held no session.
PRICE_SOURCES = ["bse_bhavcopy_equity", "nse_bhavcopy_equity"]

State = Literal["fresh", "stale", "updating", "failed", "unknown"]

LATEST_VENUE_DAYS = text(
    "select distinct on (venue) venue, trade_date, is_complete, bars from mart_trading_days"
    " order by venue, trade_date desc"
)
# A cancelled run ended before it judged anything, so the run before it stands.
LAST_RUN = text(
    "select flow, first_day, last_day, started_at, ended_at, outcome, checks_passed, failed_steps,"
    " jsonb_array_length(failures) as failed_fetches,"
    " jsonb_array_length(failed_checks) as failed_checks,"
    " jsonb_array_length(warned_checks) as warned_checks"
    " from flow_run where outcome <> 'cancelled' order by started_at desc limit 1"
)
# The request waiting or running; the flows take one at a time.
ACTIVE_REQUEST = text(
    "select id, flow, first_day, last_day, status, cancel_requested_at is not null as is_cancelling,"
    " requested_at, started_at from flow_request where status in ('requested', 'started')"
    " order by id desc limit 1"
)
# Runs of the bootstrap end on different days, the older years last.
LAST_DAY_RUN = text("select max(last_day) from flow_run")
NEVER_ASKED = text(
    "select count(*) from generate_series("
    " (select min(first_day) from mart_sources where source_id = any(:prices)),"
    " cast(:last_day as date), interval '1 day') as day"
    " where not exists (select from mart_source_days where trade_date = day::date)"
)
FIRST_DAY_WITHOUT_FIGURES = text(
    "select day::date from generate_series(cast(:after as date), cast(:until as date),"
    " interval '1 day') as day"
    " where extract(isodow from day) < 6"
    " and (select count(*) from mart_source_days where trade_date = day::date"
    " and source_id = any(:prices) and outcome = 'not_published') < cardinality(:prices)"
    " order by day limit 1"
)


@dataclass(frozen=True)
class VenueDay:
    venue: str
    latest_day: date
    is_complete: bool
    bars: int


@dataclass(frozen=True)
class LastRun:
    """The newest run not cancelled, with the counts its report gave."""

    flow: str
    first_day: date
    last_day: date
    started_at: datetime
    ended_at: datetime
    outcome: str
    checks_passed: int
    failed_steps: list[str]
    failed_stages: list[str]
    failed_fetches: int
    failed_checks: int
    warned_checks: int


@dataclass(frozen=True)
class RunningSync:
    """The request waiting or running: requested, running or cancelling, its days, and while it
    runs the stage it is in and the time left."""

    flow: str
    first_day: date
    last_day: date
    status: str
    requested_at: datetime
    started_at: datetime | None
    current_stage: str | None
    time_left: "Duration | None"


@dataclass(frozen=True)
class DataStatus:
    state: State
    published_day: date | None
    venues: tuple[VenueDay, ...]
    last_run: LastRun | None
    stale_since: date | None
    days_never_asked: int
    running: RunningSync | None


def india_now() -> datetime:
    return datetime.now(INDIA)


def last_day_due(now: datetime) -> date:
    """The latest day whose files were due by `now`: yesterday after 07:30, else the day before."""
    today = now.astimezone(INDIA).date()
    return today - timedelta(days=1 if now.astimezone(INDIA).time() >= FILES_DUE else 2)


async def data_status(database: Database) -> DataStatus:
    now = india_now()

    async def resolve(transaction: AsyncSession) -> DataStatus:
        return await resolve_data_status(transaction, now)

    return await read_marts(database, resolve)


async def resolve_data_status(transaction: AsyncSession, now: datetime) -> DataStatus:
    published_day = (await transaction.execute(PUBLISHED)).one_or_none()
    published = published_day.trade_date if published_day else None
    # The progress read builds on the estimates, which read this module's clock.
    from api.services import flow_run_progress

    venues = tuple(
        VenueDay(row.venue, row.trade_date, row.is_complete, row.bars)
        for row in await transaction.execute(LATEST_VENUE_DAYS)
    )
    run = (await transaction.execute(LAST_RUN)).one_or_none()
    last_run = None
    if run is not None:
        stages = sorted({flow_run_progress.stage_of(step) for step in run.failed_steps})
        last_run = LastRun(**run._asdict(), failed_stages=stages)
    running = None
    active = (await transaction.execute(ACTIVE_REQUEST)).one_or_none()
    if active is not None:
        progress = await flow_run_progress.resolve_progress(transaction, active.id)
        running = RunningSync(
            flow=active.flow,
            first_day=active.first_day,
            last_day=active.last_day,
            status=progress.status if progress else "requested",
            requested_at=active.requested_at,
            started_at=active.started_at,
            current_stage=progress.current_stage if progress else None,
            time_left=progress.time_left if progress else None,
        )

    stale_since = None
    if published is not None and published < last_day_due(now):
        stale_since = (
            await transaction.execute(
                FIRST_DAY_WITHOUT_FIGURES,
                {
                    "after": published + timedelta(days=1),
                    "until": last_day_due(now),
                    "prices": PRICE_SOURCES,
                },
            )
        ).scalar_one_or_none()

    last_day = (await transaction.execute(LAST_DAY_RUN)).scalar_one_or_none()
    never_asked = 0
    if last_day is not None:
        never_asked = (
            await transaction.execute(NEVER_ASKED, {"last_day": last_day, "prices": PRICE_SOURCES})
        ).scalar_one()

    return DataStatus(
        state=state_of(last_run, stale_since, running),
        published_day=published,
        venues=venues,
        last_run=last_run,
        stale_since=stale_since,
        days_never_asked=never_asked,
        running=running,
    )


def state_of(
    last_run: LastRun | None, stale_since: date | None, running: RunningSync | None
) -> State:
    """Unknown with no run recorded and none running; else the first that applies: failed,
    stale, updating, fresh."""
    if last_run is None and running is None:
        return "unknown"
    if last_run is not None and last_run.outcome == "failed":
        return "failed"
    if stale_since is not None:
        return "stale"
    return "updating" if running is not None else "fresh"
