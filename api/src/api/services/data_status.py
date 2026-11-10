"""How current the market data is: the day the pages show, each venue's latest day, the last run of
a flow, and the state they make."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts
from api.services.trading_days import PUBLISHED

State = Literal["fresh", "failed", "unknown"]

LATEST_VENUE_DAYS = text(
    "select distinct on (venue) venue, trade_date, is_complete from mart_trading_days"
    " order by venue, trade_date desc"
)
# A cancelled run ended before it judged anything, so the run before it stands.
LAST_RUN = text(
    "select flow, first_day, last_day, started_at, ended_at, outcome, failed_steps,"
    " jsonb_array_length(failures) as failed_fetches,"
    " jsonb_array_length(failed_checks) as failed_checks,"
    " jsonb_array_length(warned_checks) as warned_checks"
    " from flow_run where outcome <> 'cancelled' order by started_at desc limit 1"
)


@dataclass(frozen=True)
class VenueDay:
    venue: str
    latest_day: date
    is_complete: bool


@dataclass(frozen=True)
class LastRun:
    """The newest run not cancelled, with the counts its report gave."""

    flow: str
    first_day: date
    last_day: date
    started_at: datetime
    ended_at: datetime
    outcome: str
    failed_steps: list[str]
    failed_fetches: int
    failed_checks: int
    warned_checks: int


@dataclass(frozen=True)
class DataStatus:
    state: State
    published_day: date | None
    venues: tuple[VenueDay, ...]
    last_run: LastRun | None


async def data_status(database: Database) -> DataStatus:
    return await read_marts(database, resolve_data_status)


async def resolve_data_status(transaction: AsyncSession) -> DataStatus:
    published_day = (await transaction.execute(PUBLISHED)).one_or_none()
    venues = tuple(
        VenueDay(row.venue, row.trade_date, row.is_complete)
        for row in await transaction.execute(LATEST_VENUE_DAYS)
    )
    run = (await transaction.execute(LAST_RUN)).one_or_none()
    last_run = LastRun(**run._asdict()) if run else None
    return DataStatus(
        state=state_of(last_run),
        published_day=published_day.trade_date if published_day else None,
        venues=venues,
        last_run=last_run,
    )


def state_of(last_run: LastRun | None) -> State:
    """Failed when the last run failed; unknown with no run recorded; else fresh."""
    if last_run is None:
        return "unknown"
    return "failed" if last_run.outcome == "failed" else "fresh"
