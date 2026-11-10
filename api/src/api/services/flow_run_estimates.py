"""How long a sync would take to ask for its days: the days each daily file would be asked for, one
request every two seconds per source with the sources side by side."""

import math
from dataclasses import dataclass
from datetime import date

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
class SyncEstimate:
    requests: Requests


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
        return SyncEstimate(await requests_over(transaction, first, last, RECHECKED_DAYS))

    return await read_marts(database, estimate)
