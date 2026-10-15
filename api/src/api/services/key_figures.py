"""An instrument's newest day at one venue, as its key figures show it."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts
from api.services.price_history import LAST_DAY, number

# Each venue's figures are read from its bhavcopy and its delivery file.
PRICE_SOURCES = {"BSE": "bse_bhavcopy_equity", "NSE": "nse_bhavcopy_equity"}
DELIVERY_SOURCES = {"BSE": "bse_delivery", "NSE": "nse_delivery"}

CURRENT = text(
    "select current_isin,"
    " (select trade_date from feature_release order by release_id desc limit 1) as published_day"
    " from mart_instruments where isin = :isin"
)
# Every view is named its instrument and day, so each reads that day alone.
DAY = text(
    """
    select
        bars.open, bars.high, bars.low, bars.close, bars.previous_close, bars.volume,
        bars.turnover, bars.trade_count, figures.change_1d, figures.return_1d,
        figures.delivery_pct_1d, spread.venue_spread_bps, features.is_diverging,
        verdicts.is_complete
    from mart_price_daily as bars
    left join mart_venue_daily_figures as figures
        on figures.isin = :current and figures.venue = :venue and figures.trade_date = :day
    left join mart_venue_spread as spread
        on spread.isin = :isin and spread.trade_date = :day
    left join mart_daily_features as features
        on features.isin = :current and features.trade_date = :day
    left join mart_trading_days as verdicts
        on verdicts.venue = :venue and verdicts.trade_date = :day
    where bars.isin = :isin and bars.venue = :venue and bars.trade_date = :day
    """
)
SOURCES = text(
    "select source_id, tier, sebi_curation_ref from mart_sources where source_id = any(:sources)"
)


@dataclass(frozen=True)
class Source:
    source_id: str
    tier: int
    sebi_curation_ref: str | None


@dataclass(frozen=True)
class KeyFigures:
    """The venue's newest day up to the published day as traded, its change on the adjusted series,
    its delivery share, the spread to the other venue, the day's verdict, and the sources read; every
    figure absent where the instrument never traded at the venue."""

    isin: str
    venue: str
    trade_date: date | None = None
    is_stale: bool | None = None
    is_day_complete: bool | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    previous_close: float | None = None
    volume: int | None = None
    turnover: float | None = None
    trade_count: int | None = None
    change_1d: float | None = None
    return_1d: float | None = None
    delivery_pct_1d: float | None = None
    venue_spread_bps: float | None = None
    is_diverging: bool | None = None
    sources: tuple[Source, ...] = ()


def sources_read(venue: str, delivery: Decimal | float | None, spread: Decimal | None) -> list[str]:
    """The sources behind the figures shown: the venue's bhavcopy, its delivery file where it gave a
    figure, and the other venue's bhavcopy where a spread is shown."""
    other = next(name for name in PRICE_SOURCES if name != venue)
    return [
        PRICE_SOURCES[venue],
        *([DELIVERY_SOURCES[venue]] if delivery is not None else []),
        *([PRICE_SOURCES[other]] if spread is not None else []),
    ]


async def key_figures(database: Database, isin: str, venue: str) -> KeyFigures | None:
    async def read(transaction: AsyncSession) -> KeyFigures | None:
        found = (await transaction.execute(CURRENT, {"isin": isin})).one_or_none()
        if found is None:
            return None
        scope = {"isin": isin, "current": found.current_isin, "venue": venue}
        day = (await transaction.execute(LAST_DAY, scope)).scalar_one()
        if day is None:
            return KeyFigures(isin, venue)
        row = (await transaction.execute(DAY, scope | {"day": day})).one()
        names = sources_read(venue, row.delivery_pct_1d, row.venue_spread_bps)
        listed = {
            source.source_id: Source(*source)
            for source in await transaction.execute(SOURCES, {"sources": names})
        }
        return KeyFigures(
            isin=isin,
            venue=venue,
            trade_date=day,
            is_stale=found.published_day is not None and day < found.published_day,
            is_day_complete=row.is_complete,
            open=number(row.open),
            high=number(row.high),
            low=number(row.low),
            close=number(row.close),
            previous_close=number(row.previous_close),
            volume=row.volume,
            turnover=number(row.turnover),
            trade_count=row.trade_count,
            change_1d=row.change_1d,
            return_1d=row.return_1d,
            delivery_pct_1d=row.delivery_pct_1d,
            venue_spread_bps=number(row.venue_spread_bps),
            is_diverging=row.is_diverging,
            sources=tuple(listed[name] for name in names if name in listed),
        )

    return await read_marts(database, read)
