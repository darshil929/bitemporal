"""The market's day in summary: breadth across the companies that traded, and the companies that
moved most past the liquidity gate, on the latest day complete at every venue in session."""

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.daily_feature_rows import SYMBOL, UNHANDLED_ACTIONS, UNHANDLED_ACTIONS_JOIN
from api.services.key_figures import DELIVERY_SOURCES, PRICE_SOURCES, SOURCES, Source
from api.services.market_reads import read_marts
from api.services.screener_queries import GATE_RUPEES
from api.services.trading_days import resolve_market_day

MOVERS = 5
LARGEST_BELOW_GATE = 3
# A day's return reads the bar before it.
RETURN_LOOKBACK_BARS = 1

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
class MovedMost:
    """The companies that moved most one way past the gate. Those below the gate that moved further
    than the last of them: the largest moves, and how many more. A company with no twenty-day average
    is neither past the gate nor below it."""

    rows: tuple[dict[str, Any], ...] = ()
    below_gate: tuple[dict[str, Any], ...] = ()
    more_below_gate: int = 0


@dataclass(frozen=True)
class MarketSummary:
    day: date | None = None
    breadth: Breadth | None = None
    moved_up: MovedMost = MovedMost()
    moved_down: MovedMost = MovedMost()
    breadth_sources: tuple[Source, ...] = ()
    mover_sources: tuple[Source, ...] = ()


def moved_most(direction: Literal["up", "down"]) -> TextClause:
    """Only a rise ranks up and only a fall down, so a one-sided day lists fewer than five. Fewer than
    five leaves no last mover to pass, and any move of that sign below the gate would have ranked."""
    sign, order, last = (">", "desc", "min") if direction == "up" else ("<", "asc", "max")
    return text(
        f"""
        with moved as materialized (
            select features.*, coalesce(instruments.display_name, instruments.name) as display_name
            from mart_daily_features as features
            inner join mart_instruments as instruments on instruments.isin = features.isin
            where features.trade_date = :day and features.isin like 'INE%'
                and features.return_1d {sign} 0
        ),
        movers as (
            select * from moved where adtv_20d >= :gate
            order by return_1d {order}, isin
            limit :movers
        ),
        below_gate as (
            select isin, display_name, return_1d from moved
            where adtv_20d < :gate and (
                (select count(*) from movers) < :movers
                or return_1d {sign} (select {last}(return_1d) from movers)
            )
        ),
        counted as (
            select
                (select count(*) from below_gate) as below_gate_count,
                coalesce(
                    (
                        select jsonb_agg(largest) from (
                            select * from below_gate
                            order by abs(return_1d) desc, isin
                            limit :largest
                        ) as largest
                    ),
                    cast('[]' as jsonb)
                ) as below_gate
        )
        select counted.below_gate_count, counted.below_gate, shown.*
        from counted left join lateral (
            select
                features.isin, features.display_name, features.primary_venue, features.close,
                features.return_1d, features.volume_ratio_20d, features.delivery_pct_1d,
                {SYMBOL},
                {UNHANDLED_ACTIONS}
            from movers as features
            {UNHANDLED_ACTIONS_JOIN}
            order by features.return_1d {order}, features.isin
        ) as shown on true
        """
    )


async def read_moved_most(
    transaction: AsyncSession, direction: Literal["up", "down"], day: date
) -> MovedMost:
    found = (
        await transaction.execute(
            moved_most(direction),
            {
                "day": day,
                "gate": GATE_RUPEES,
                "movers": MOVERS,
                "largest": LARGEST_BELOW_GATE,
                "lookback": RETURN_LOOKBACK_BARS,
            },
        )
    ).all()
    largest = tuple(found[0].below_gate)
    return MovedMost(
        rows=tuple(dict(row._mapping) for row in found if row.isin is not None),
        below_gate=largest,
        more_below_gate=found[0].below_gate_count - len(largest),
    )


async def market_summary(database: Database) -> MarketSummary:
    async def read(transaction: AsyncSession) -> MarketSummary:
        day = (await resolve_market_day(transaction)).last_complete_day
        if day is None:
            return MarketSummary()
        breadth = (await transaction.execute(BREADTH, {"day": day})).one_or_none()
        bhavcopies = list(PRICE_SOURCES.values())
        names = [*bhavcopies, *DELIVERY_SOURCES.values()]
        listed = {
            source.source_id: Source(*source)
            for source in await transaction.execute(SOURCES, {"sources": names})
        }
        return MarketSummary(
            day=day,
            breadth=Breadth(*breadth) if breadth else None,
            moved_up=await read_moved_most(transaction, "up", day),
            moved_down=await read_moved_most(transaction, "down", day),
            breadth_sources=tuple(listed[name] for name in bhavcopies if name in listed),
            mover_sources=tuple(listed[name] for name in names if name in listed),
        )

    return await read_marts(database, read)
