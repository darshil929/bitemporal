"""The trading day the market pages show, and how each venue's session that day stands."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts

# The newest release is the computation the daily features view reads: a publish replaces the view
# and records its release in one transaction.
PUBLISHED = text(
    "select trade_date, published_at from feature_release order by release_id desc limit 1"
)
VERDICTS = text(
    "select venue, is_complete from mart_trading_days where trade_date = :day order by venue"
)
# A day is complete where every venue that held a session completed it.
LAST_COMPLETE = text(
    "select trade_date from mart_trading_days where trade_date <= :day"
    " group by trade_date having bool_and(is_complete) order by trade_date desc limit 1"
)


@dataclass(frozen=True)
class VenueSession:
    venue: str
    is_complete: bool


@dataclass(frozen=True)
class MarketDay:
    """The day the daily features describe, when they were published, each venue's verdict on that
    day, and the latest day up to it complete at every venue in session; all absent before the first
    publish."""

    published_day: date | None
    published_at: datetime | None
    venues: tuple[VenueSession, ...]
    last_complete_day: date | None


NO_FIGURES = MarketDay(published_day=None, published_at=None, venues=(), last_complete_day=None)


async def market_day(database: Database) -> MarketDay:
    return await read_marts(database, resolve_market_day)


async def resolve_market_day(transaction: AsyncSession) -> MarketDay:
    release = (await transaction.execute(PUBLISHED)).one_or_none()
    if release is None or release.trade_date is None:
        return NO_FIGURES
    day = {"day": release.trade_date}
    venues = tuple(
        VenueSession(row.venue, row.is_complete) for row in await transaction.execute(VERDICTS, day)
    )
    if venues and all(session.is_complete for session in venues):
        last_complete_day = release.trade_date
    else:
        last_complete_day = (await transaction.execute(LAST_COMPLETE, day)).scalar_one_or_none()
    return MarketDay(release.trade_date, release.published_at, venues, last_complete_day)
