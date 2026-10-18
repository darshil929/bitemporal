"""Instruments passing a screen of their daily features, on the latest day complete at every venue
in session."""

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from psycopg.errors import QueryCanceled
from sqlalchemy import TextClause, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts
from api.services.trading_days import resolve_market_day

# The figures a screen compares, filters and sorts on, each one comparable across instruments; price
# levels, the close and its averages and bands, are not. The names are columns of the daily
# features, and with the comparisons below they are the only text of a screen not bound as a value.
FIGURES = frozenset(
    {
        "return_1d", "return_1w", "return_1m", "return_3m", "return_6m", "return_1y",
        "momentum_12_1", "volatility_20d", "rsi_14", "adtv_20d", "volume_ratio_20d",
        "delivery_pct_1d", "delivery_pct_20d", "from_52w_high", "venue_spread_bps",
    }
)  # fmt: skip
FLAGS = frozenset({"is_52w_high", "is_52w_low"})
COMPARISONS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
DIRECTIONS = {"asc": "asc", "desc": "desc"}

# The liquidity gate: twenty days' average traded value of at least ₹25 crore, on unless removed.
GATE_FIGURE = "adtv_20d"
GATE_RUPEES = 250_000_000.0
# With no sort named, the most traded instruments come first.
DEFAULT_SORT = ("adtv_20d", "desc")
PAGE_SIZE = 50
ROW_CAP = 500
PAGES = ROW_CAP // PAGE_SIZE
QUERY_TIMEOUT = "10s"

Kind = Literal["companies", "all"]
Value = float | bool


class ScreenRefused(Exception):
    """A part of a screen naming no figure, comparison or value it may use."""

    def __init__(self, reason: str, part: str) -> None:
        super().__init__(reason, part)
        self.reason = reason
        self.part = part


class ScreenTimedOut(Exception):
    """A screen ran past the time a query may take."""


@dataclass(frozen=True)
class Criterion:
    figure: str
    comparison: str
    value: Value


@dataclass(frozen=True)
class Screen:
    gate: Criterion | None
    kind: Kind
    criteria: tuple[Criterion, ...]
    sort: tuple[str, str]
    page: int

    @property
    def figures(self) -> tuple[str, ...]:
        """The figures shown beside each instrument: the gate's, each criterion's, the sort's."""
        named = [*(item.figure for item in (self.gate, *self.criteria) if item), self.sort[0]]
        return tuple(dict.fromkeys(named))


def criterion(part: str) -> Criterion:
    """A criterion written `figure:comparison:value`; a flag takes `eq` and `true` or `false`."""
    pieces = part.split(":")
    if len(pieces) != 3:
        raise ScreenRefused("malformed_criterion", part)
    figure, comparison, value = pieces
    if figure in FLAGS:
        if comparison != "eq" or value not in ("true", "false"):
            raise ScreenRefused("malformed_criterion", part)
        return Criterion(figure, "eq", value == "true")
    if figure not in FIGURES:
        raise ScreenRefused("unknown_figure", part)
    if comparison not in COMPARISONS:
        raise ScreenRefused("unknown_comparison", part)
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ScreenRefused("malformed_value", part)
    return Criterion(figure, comparison, number)


def screen_from(
    gate: str | None, kind: Kind, criteria: list[str], sort: str | None, page: int
) -> Screen:
    """The screen a query string asks for; the gate is on unless `none`, and only on traded value."""
    if gate is None:
        gated: Criterion | None = Criterion(GATE_FIGURE, "gte", GATE_RUPEES)
    elif gate == "none":
        gated = None
    else:
        gated = criterion(gate)
        if gated.figure != GATE_FIGURE:
            raise ScreenRefused("malformed_gate", gate)
    order = DEFAULT_SORT
    if sort is not None:
        figure, _, direction = sort.partition(":")
        if figure not in FIGURES or direction not in DIRECTIONS:
            raise ScreenRefused("unknown_sort", sort)
        order = (figure, direction)
    return Screen(gated, kind, tuple(criterion(part) for part in criteria), order, page)


@dataclass(frozen=True)
class ScreenResult:
    """A page of the instruments passing a screen, and how many pass it in all."""

    day: date | None
    matched: int
    page: int
    rows: tuple[dict[str, Any], ...]


def statement(screen: Screen) -> tuple[TextClause, dict[str, Any]]:
    conditions = ["features.trade_date = :day"]
    if screen.kind == "companies":
        conditions.append("features.isin like 'INE%'")
    values: dict[str, Any] = {}
    for index, item in enumerate(item for item in (screen.gate, *screen.criteria) if item):
        comparison = "=" if item.comparison == "eq" else COMPARISONS[item.comparison]
        conditions.append(f"features.{item.figure} {comparison} :value_{index}")
        values[f"value_{index}"] = item.value
    shown = ", ".join(f"'{figure}', features.{figure}" for figure in screen.figures)
    figure, direction = screen.sort
    # The count comes from every instrument passing; the page from the rows in the sort's order.
    sql = f"""
        with passing as (
            select features.*, coalesce(instruments.display_name, instruments.name) as display_name
            from mart_daily_features as features
            inner join mart_instruments as instruments on instruments.isin = features.isin
            where {" and ".join(conditions)}
        ),
        counted as (select count(*) as matched from passing)
        select counted.matched, shown.*
        from counted left join lateral (
            select
                features.isin, features.display_name, features.primary_venue, features.close,
                features.return_1d, features.venue_spread_bps, features.is_diverging,
                jsonb_build_object({shown}) as figures,
                (
                    select listings.local_symbol from mart_listings as listings
                    where listings.isin = features.isin
                    order by listings.delisting_date is null desc,
                        listings.exchange = features.primary_venue desc,
                        listings.exchange = 'NSE' desc, listings.listing_date desc
                    limit 1
                ) as symbol
            from passing as features
            order by features.{figure} {DIRECTIONS[direction]} nulls last, features.isin
            limit :limit offset :offset
        ) as shown on true
    """
    offset = (screen.page - 1) * PAGE_SIZE
    return text(sql), values | {"limit": min(PAGE_SIZE, ROW_CAP - offset), "offset": offset}


async def run_screen(database: Database, screen: Screen) -> ScreenResult:
    async def read(transaction: AsyncSession) -> ScreenResult:
        day = (await resolve_market_day(transaction)).last_complete_day
        if day is None:
            return ScreenResult(None, 0, screen.page, ())
        await transaction.execute(
            text("select set_config('statement_timeout', :timeout, true)"),
            {"timeout": QUERY_TIMEOUT},
        )
        sql, values = statement(screen)
        try:
            found = (await transaction.execute(sql, values | {"day": day})).all()
        except OperationalError as error:
            if isinstance(error.orig, QueryCanceled):
                raise ScreenTimedOut from error
            raise
        rows = tuple(dict(row._mapping) for row in found if row.isin is not None)
        return ScreenResult(day, found[0].matched, screen.page, rows)

    return await read_marts(database, read)
