"""How long a sync or the history bootstrap would take: the days each daily file would be asked for,
one request every two seconds per source with the sources side by side, and the fixed work of the
other steps as the last three runs of the flow took it."""

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services import data_status
from api.services.market_reads import read_marts

# Each daily file with its venue's price file: delivery is read from the first day prices are.
DAILY_SOURCES = {
    "bse_bhavcopy_equity": "bse_bhavcopy_equity",
    "nse_bhavcopy_equity": "nse_bhavcopy_equity",
    "bse_delivery": "bse_bhavcopy_equity",
    "nse_delivery": "nse_bhavcopy_equity",
}
REQUEST_SECONDS = 2
# A sync asks again for the two most recent days each source holds, in case a file was corrected.
RECHECKED_DAYS = 2
# The bootstrap's first run covers the two most recent years.
RECENT = timedelta(days=730)
MEASURED_RUNS = 3

# The steps that fetch from the venues; every other step is fixed work.
FETCH_STEPS = frozenset(
    {
        "source_registry",
        "bse_bhavcopy",
        "nse_bhavcopy",
        "bse_delivery",
        "nse_delivery",
        "corporate_actions",
        "nse_corporate_actions",
        "bse_instrument_names",
        "nse_instrument_names",
    }
)

FIRST_DAY = text("select min(first_day) from mart_sources where source_id = any(:prices)")
SOURCE_DAYS = text(
    "select pair.source_id, count(day) as days,"
    " count(day) filter (where held.outcome = 'succeeded') as held"
    " from unnest(cast(:sources as text[]), cast(:venues as text[])) as pair(source_id, venue_id)"
    " join mart_sources as own on own.source_id = pair.source_id"
    " join mart_sources as venue on venue.source_id = pair.venue_id"
    " cross join generate_series(cast(:first as date), cast(:last as date), interval '1 day') as day"
    " left join mart_source_days as held"
    " on held.source_id = pair.source_id and held.trade_date = day::date"
    " where day::date >= greatest(own.first_day, venue.first_day)"
    " group by pair.source_id order by pair.source_id"
)
RECENT_RUN_STEPS = text(
    "with recent as ("
    " select run_id, started_at, ended_at from flow_run"
    " where flow = :flow and outcome <> 'cancelled'"
    " and exists (select from flow_run_step where flow_run_step.run_id = flow_run.run_id)"
    " order by started_at desc limit :runs)"
    " select recent.run_id, extract(epoch from recent.ended_at - recent.started_at) as total,"
    " step.step, extract(epoch from step.ended_at - step.started_at) as seconds"
    " from recent join flow_run_step as step on step.run_id = recent.run_id"
    " where step.started_at is not null"
)


class RangeRefused(Exception):
    """A range of days no flow can run over."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Duration:
    seconds: int

    @property
    def minutes(self) -> int:
        """Whole minutes, rounded up."""
        return math.ceil(self.seconds / 60)


@dataclass(frozen=True)
class SourceDays:
    source_id: str
    days: int
    held: int
    to_request: int


@dataclass(frozen=True)
class Requests:
    first_day: date
    last_day: date
    sources: tuple[SourceDays, ...]
    duration: Duration


@dataclass(frozen=True)
class FixedWork:
    """The median of the last runs' other steps, by stage, and those runs' whole durations."""

    stages: dict[str, Duration]
    duration: Duration
    last_runs: tuple[Duration, ...]


@dataclass(frozen=True)
class SyncEstimate:
    requests: Requests
    fixed: FixedWork | None


@dataclass(frozen=True)
class BootstrapEstimate:
    windows: tuple[Requests, ...]
    fixed: FixedWork | None


def stage_of(step: str) -> str:
    if step == "dbt_models":
        return "models"
    return "features" if step.startswith("daily_feature") else "other"


async def first_day(transaction: AsyncSession) -> date | None:
    found: date | None = (
        await transaction.execute(FIRST_DAY, {"prices": data_status.PRICE_SOURCES})
    ).scalar_one_or_none()
    return found


async def requests_over(
    transaction: AsyncSession, first: date, last: date, rechecked: int
) -> Requests:
    rows = await transaction.execute(
        SOURCE_DAYS,
        {
            "first": first,
            "last": last,
            "sources": list(DAILY_SOURCES),
            "venues": list(DAILY_SOURCES.values()),
        },
    )
    sources = tuple(
        SourceDays(
            row.source_id,
            row.days,
            row.held,
            row.days - row.held + min(rechecked, row.held),
        )
        for row in rows
    )
    longest = max((source.to_request for source in sources), default=0)
    return Requests(first, last, sources, Duration(longest * REQUEST_SECONDS))


async def fixed_work(transaction: AsyncSession, flow: str) -> FixedWork | None:
    totals: dict[str, float] = {}
    stages: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in await transaction.execute(RECENT_RUN_STEPS, {"flow": flow, "runs": MEASURED_RUNS}):
        totals[row.run_id] = float(row.total)
        if row.step not in FETCH_STEPS:
            stages[row.run_id][stage_of(row.step)] += float(row.seconds)
    if not totals:
        return None
    names = sorted({stage for run in stages.values() for stage in run})
    return FixedWork(
        stages={
            name: Duration(round(statistics.median(stages[run][name] for run in totals)))
            for name in names
        },
        duration=Duration(round(statistics.median(sum(stages[run].values()) for run in totals))),
        last_runs=tuple(Duration(round(total)) for total in totals.values()),
    )


async def check_range(transaction: AsyncSession, first: date, last: date) -> None:
    """Refuse a range reversed, starting before the history, or ending after today in India."""
    start = await first_day(transaction)
    if last < first:
        raise RangeRefused("range_reversed")
    if start is not None and first < start:
        raise RangeRefused("before_history")
    if last > data_status.india_now().date():
        raise RangeRefused("after_today")


async def sync_estimate(database: Database, first: date, last: date) -> SyncEstimate:
    async def estimate(transaction: AsyncSession) -> SyncEstimate:
        await check_range(transaction, first, last)
        requests = await requests_over(transaction, first, last, RECHECKED_DAYS)
        return SyncEstimate(requests, await fixed_work(transaction, "sync"))

    return await read_marts(database, estimate)


async def bootstrap_estimate(database: Database) -> BootstrapEstimate:
    """The two most recent years ending today in India, then every earlier day of the history."""

    async def estimate(transaction: AsyncSession) -> BootstrapEstimate:
        today = data_status.india_now().date()
        start = await first_day(transaction) or today
        split = today - RECENT
        bounds = (
            [(split + timedelta(days=1), today), (start, split)]
            if start <= split
            else [(start, today)]
        )
        windows = tuple([await requests_over(transaction, a, b, 0) for a, b in bounds])
        return BootstrapEstimate(windows, await fixed_work(transaction, "bootstrap"))

    return await read_marts(database, estimate)
