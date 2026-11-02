"""The market's day in summary: breadth across the companies that traded, on the latest day complete
at every venue in session."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.key_figures import PRICE_SOURCES, SOURCES, Source
from api.services.market_reads import read_marts
from api.services.trading_days import resolve_market_day

BREADTH = text(
    """
    select
        (
            select count(*) from mart_daily_features
            where trade_date = :day and isin like 'INE%'
        ) as companies,
        advancing, declining, unchanged, new_52w_highs, new_52w_lows, median_return_1d
    from mart_market_breadth
    where trade_date = :day
    """
)


@dataclass(frozen=True)
class Breadth:
    companies: int
    advancing: int
    declining: int
    unchanged: int
    new_52w_highs: int
    new_52w_lows: int
    median_return_1d: float | None


@dataclass(frozen=True)
class MarketSummary:
    day: date | None = None
    breadth: Breadth | None = None
    breadth_sources: tuple[Source, ...] = ()


async def market_summary(database: Database) -> MarketSummary:
    async def read(transaction: AsyncSession) -> MarketSummary:
        day = (await resolve_market_day(transaction)).last_complete_day
        if day is None:
            return MarketSummary()
        breadth = (await transaction.execute(BREADTH, {"day": day})).one_or_none()
        bhavcopies = list(PRICE_SOURCES.values())
        listed = {
            source.source_id: Source(*source)
            for source in await transaction.execute(SOURCES, {"sources": bhavcopies})
        }
        return MarketSummary(
            day=day,
            breadth=Breadth(*breadth) if breadth else None,
            breadth_sources=tuple(listed[name] for name in bhavcopies if name in listed),
        )

    return await read_marts(database, read)
