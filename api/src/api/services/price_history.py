"""An instrument's daily series at one venue, as its price chart draws it."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts

RANGE_MONTHS: dict[str, int | None] = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "All": None}

OVERLAYS = (
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_20",
    "ema_50",
    "bollinger_20_upper",
    "bollinger_20_lower",
)

LINEAGE = text(
    "select lineage.isin, lineage.current_isin from mart_instruments as requested"
    " inner join mart_instruments as lineage on lineage.current_isin = requested.current_isin"
    " where requested.isin = :isin"
)
# A replaced ISIN's series is its own bars, kept under the ISIN that took it over. The series ends
# on the published day, which a sync whose checks failed leaves where it was.
LAST_DAY = text(
    "select max(trade_date) from mart_adjusted_prices"
    " where isin = :current and venue = :venue and (source_isin = :isin or :isin = :current)"
    " and trade_date <= coalesce("
    "(select trade_date from feature_release order by release_id desc limit 1), 'infinity')"
)
# The spread is keyed on the ISIN each bar was published under; naming those ISINs lets its view
# read their bars alone.
SERIES = text(
    """
    select
        bars.trade_date, bars.open, bars.high, bars.low, bars.close, bars.close_as_traded,
        bars.adjustment_factor, bars.volume, bars.delivery_quantity,
        other.close as other_venue_close, spread.venue_spread_bps, features.is_diverging,
        features.primary_venue, features.sma_20, features.sma_50, features.sma_200,
        features.ema_20, features.ema_50, features.bollinger_20_upper, features.bollinger_20_lower
    from mart_adjusted_prices as bars
    left join mart_adjusted_prices as other
        on other.isin = bars.isin and other.trade_date = bars.trade_date
        and other.venue <> bars.venue and other.trade_date > :after
        and other.trade_date <= :last_day
    left join mart_venue_spread as spread
        on spread.isin = bars.source_isin and spread.trade_date = bars.trade_date
        and spread.isin = any(:lineage) and spread.trade_date > :after
        and spread.trade_date <= :last_day
    left join mart_daily_features as features
        on features.isin = bars.isin and features.trade_date = bars.trade_date
        and features.trade_date > :after and features.trade_date <= :last_day
    where bars.isin = :current and bars.venue = :venue
        and (bars.source_isin = :isin or :isin = :current)
        and bars.trade_date > :after and bars.trade_date <= :last_day
    order by bars.trade_date
    """
)


@dataclass(frozen=True)
class PriceDay:
    """A day's adjusted candle, volume and delivery, the close as traded and the factor between
    them, the other venue's adjusted close and the spread, and the overlays in the candle's scale
    where the day's daily features were computed on this venue."""

    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    close_as_traded: float | None
    adjustment_factor: float
    volume: float
    delivery_quantity: float | None
    other_venue_close: float | None
    venue_spread_bps: float | None
    is_diverging: bool | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_20: float | None
    ema_50: float | None
    bollinger_20_upper: float | None
    bollinger_20_lower: float | None


@dataclass(frozen=True)
class PriceHistory:
    isin: str
    venue: str
    range: str
    days: tuple[PriceDay, ...]

    @property
    def first_day(self) -> date | None:
        return self.days[0].trade_date if self.days else None

    @property
    def last_day(self) -> date | None:
        return self.days[-1].trade_date if self.days else None


def months_before(day: date, months: int) -> date:
    """The same day of the month `months` earlier, or that month's last day where it is shorter."""
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def number(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def price_day(row: Any, venue: str) -> PriceDay:
    factor = float(row.adjustment_factor)
    # The overlays are in their own day's price scale, which the bar's factor brings to the series'.
    on_venue = row.primary_venue == venue
    overlays = {name: scaled(getattr(row, name), factor) if on_venue else None for name in OVERLAYS}
    return PriceDay(
        trade_date=row.trade_date,
        open=number(row.open),
        high=number(row.high),
        low=number(row.low),
        close=number(row.close),
        close_as_traded=number(row.close_as_traded),
        adjustment_factor=factor,
        volume=float(row.volume),
        delivery_quantity=number(row.delivery_quantity),
        other_venue_close=number(row.other_venue_close),
        venue_spread_bps=number(row.venue_spread_bps),
        is_diverging=row.is_diverging,
        **overlays,
    )


async def price_history(
    database: Database, isin: str, venue: str, period: str
) -> PriceHistory | None:
    async def read(transaction: AsyncSession) -> PriceHistory | None:
        lineage = (await transaction.execute(LINEAGE, {"isin": isin})).all()
        if not lineage:
            return None
        scope = {"isin": isin, "current": lineage[0].current_isin, "venue": venue}
        last_day = (await transaction.execute(LAST_DAY, scope)).scalar_one()
        if last_day is None:
            return PriceHistory(isin, venue, period, ())
        months = RANGE_MONTHS[period]
        window = {
            "lineage": [row.isin for row in lineage],
            "after": date.min if months is None else months_before(last_day, months),
            "last_day": last_day,
        }
        rows = await transaction.execute(SERIES, scope | window)
        return PriceHistory(isin, venue, period, tuple(price_day(row, venue) for row in rows))

    return await read_marts(database, read)
