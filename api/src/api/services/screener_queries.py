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
# An instrument below it is marked whatever gate the screen sets.
GATE_FIGURE = "adtv_20d"
GATE_RUPEES = 250_000_000.0
DEFAULT_GATE = f"{GATE_FIGURE}:gte:{GATE_RUPEES:.0f}"
# With no sort named, the most traded instruments come first.
DEFAULT_SORT = ("adtv_20d", "desc")
PAGE_SIZE = 50
ROW_CAP = 500
PAGES = ROW_CAP // PAGE_SIZE
QUERY_TIMEOUT = "10s"

# A row's trend is the adjusted closes of its venue's last 64 bars, the three months a 63-bar return
# spans, and is absent while fewer exist.
TREND_BARS = 64
# The bars before the screened day a figure reaches back, where further than the trend. An unhandled
# corporate action after the earliest bar a row's figures and trend read is listed on the row.
LOOKBACK_BARS = {
    "return_6m": 126,
    "return_1y": 252,
    "momentum_12_1": 252,
    "from_52w_high": 251,
    "is_52w_high": 251,
    "is_52w_low": 251,
}

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
    # As the address writes it.
    part: str


@dataclass(frozen=True)
class Screen:
    gate: Criterion | None
    kind: Kind
    criteria: tuple[Criterion, ...]
    sort: tuple[str, str]
    page: int

    @property
    def items(self) -> tuple[Criterion, ...]:
        """The gate, where it is on, then each criterion."""
        return tuple(item for item in (self.gate, *self.criteria) if item)

    @property
    def figures(self) -> tuple[str, ...]:
        """The figures shown beside each instrument: the gate's, each criterion's, the sort's."""
        return tuple(dict.fromkeys([*(item.figure for item in self.items), self.sort[0]]))

    @property
    def lookback(self) -> int:
        """The bars before the screened day that a row's trend and shown figures read."""
        return max([TREND_BARS - 1, *(LOOKBACK_BARS.get(figure, 0) for figure in self.figures)])


def criterion(part: str) -> Criterion:
    """A criterion written `figure:comparison:value`; a flag takes `eq` and `true` or `false`."""
    pieces = part.split(":")
    if len(pieces) != 3:
        raise ScreenRefused("malformed_criterion", part)
    figure, comparison, value = pieces
    if figure in FLAGS:
        if comparison != "eq" or value not in ("true", "false"):
            raise ScreenRefused("malformed_criterion", part)
        return Criterion(figure, "eq", value == "true", part)
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
    return Criterion(figure, comparison, number, part)


def screen_from(
    gate: str | None, kind: Kind, criteria: list[str], sort: str | None, page: int
) -> Screen:
    """The screen a query string asks for; the gate is on unless `none`, and only on traded value."""
    if gate is None:
        gated: Criterion | None = criterion(DEFAULT_GATE)
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
class Strictest:
    """The criterion that alone excludes the most instruments of a screen nothing passes: how many
    pass every other criterion, of how many the day holds of the screen's kind."""

    criterion: Criterion
    is_gate: bool
    passing_the_rest: int
    screened: int


@dataclass(frozen=True)
class ScreenResult:
    """A page of the instruments passing a screen, how many pass it in all, and the strictest
    criterion where none does."""

    day: date | None
    matched: int
    page: int
    rows: tuple[dict[str, Any], ...]
    strictest: Strictest | None


def scope(screen: Screen) -> list[str]:
    """The instruments a screen compares: the day's features, of companies alone unless all."""
    scoped = ["features.trade_date = :day"]
    if screen.kind == "companies":
        scoped.append("features.isin like 'INE%'")
    return scoped


def conditions(screen: Screen) -> tuple[list[str], dict[str, Any]]:
    """Each of the screen's items as a comparison of the features, in order, its value bound."""
    tests: list[str] = []
    values: dict[str, Any] = {}
    for index, item in enumerate(screen.items):
        comparison = "=" if item.comparison == "eq" else COMPARISONS[item.comparison]
        tests.append(f"features.{item.figure} {comparison} :value_{index}")
        values[f"value_{index}"] = item.value
    return tests, values


def statement(screen: Screen) -> tuple[TextClause, dict[str, Any]]:
    tests, values = conditions(screen)
    shown = ", ".join(f"'{figure}', features.{figure}" for figure in screen.figures)
    figure, direction = screen.sort
    order = f"features.{figure} {DIRECTIONS[direction]} nulls last, features.isin"
    # The count comes from every instrument passing; the page from the rows in the sort's order. A
    # row's trend and actions are read on the venue its figures were computed on.
    sql = f"""
        with passing as (
            select features.*, coalesce(instruments.display_name, instruments.name) as display_name
            from mart_daily_features as features
            inner join mart_instruments as instruments on instruments.isin = features.isin
            where {" and ".join([*scope(screen), *tests])}
        ),
        counted as (select count(*) as matched from passing),
        page as (select * from passing as features order by {order} limit :limit offset :offset)
        select counted.matched, shown.*
        from counted left join lateral (
            select
                features.isin, features.display_name, features.primary_venue, features.close,
                features.return_1d, features.venue_spread_bps, features.is_diverging,
                not (features.adtv_20d >= :gate_rupees) as is_below_gate,
                jsonb_build_object({shown}) as figures,
                (
                    select listings.local_symbol from mart_listings as listings
                    where listings.isin = features.isin
                    order by listings.delisting_date is null desc,
                        listings.exchange = features.primary_venue desc,
                        listings.exchange = 'NSE' desc, listings.listing_date desc
                    limit 1
                ) as symbol,
                trend.closes as trend_3m,
                coalesce(unhandled.actions, cast('[]' as jsonb)) as unhandled_actions
            from page as features
            left join lateral (
                select
                    case
                        when count(*) = :trend_bars
                            then array_agg(bars.close order by bars.trade_date)
                    end as closes
                from (
                    select bars.trade_date, bars.close from mart_adjusted_prices as bars
                    where bars.isin = features.isin and bars.venue = features.primary_venue
                        and bars.trade_date <= features.trade_date and bars.close is not null
                    order by bars.trade_date desc
                    limit :trend_bars
                ) as bars
            ) as trend on true
            left join lateral (
                select coalesce(
                    (
                        select bars.trade_date from mart_adjusted_prices as bars
                        where bars.isin = features.isin and bars.venue = features.primary_venue
                            and bars.trade_date <= features.trade_date
                        order by bars.trade_date desc
                        offset :lookback limit 1
                    ),
                    (
                        select bars.trade_date from mart_adjusted_prices as bars
                        where bars.isin = features.isin and bars.venue = features.primary_venue
                        order by bars.trade_date
                        limit 1
                    )
                ) as first_day
            ) as span on true
            left join lateral (
                select jsonb_agg(
                    jsonb_build_object('ex_date', actions.ex_date, 'purpose', actions.purpose)
                    order by actions.ex_date desc, actions.purpose
                ) as actions
                from mart_corporate_actions as actions
                where actions.isin = features.isin and actions.action_type = 'unhandled'
                    and actions.ex_date > span.first_day and actions.ex_date <= features.trade_date
            ) as unhandled on true
            order by {order}
        ) as shown on true
    """
    offset = (screen.page - 1) * PAGE_SIZE
    return text(sql), values | {
        "limit": min(PAGE_SIZE, ROW_CAP - offset),
        "offset": offset,
        "gate_rupees": GATE_RUPEES,
        "trend_bars": TREND_BARS,
        "lookback": screen.lookback,
    }


def rest_statement(screen: Screen) -> tuple[TextClause, dict[str, Any]]:
    """How many instruments the day holds of the screen's kind, and how many pass every item of the
    screen but each one in turn."""
    tests, values = conditions(screen)
    rests = "".join(
        f", count(*) filter (where {' and '.join([*tests[:index], *tests[index + 1 :]]) or 'true'})"
        for index in range(len(tests))
    )
    sql = f"""
        select count(*) as screened{rests}
        from mart_daily_features as features
        inner join mart_instruments as instruments on instruments.isin = features.isin
        where {" and ".join(scope(screen))}
    """
    return text(sql), values


def strictest(screen: Screen, screened: int, passing_the_rest: list[int]) -> Strictest | None:
    """The item whose removal admits the most, the earlier on a tie; the gate only where removing no
    other criterion admits any."""
    gated = screen.gate is not None
    admitting = [(index, count) for index, count in enumerate(passing_the_rest) if count > 0]
    candidates = [pair for pair in admitting if not (gated and pair[0] == 0)] or admitting
    if not candidates:
        return None
    index, count = max(candidates, key=lambda pair: pair[1])
    return Strictest(screen.items[index], gated and index == 0, count, screened)


async def run_screen(database: Database, screen: Screen) -> ScreenResult:
    async def read(transaction: AsyncSession) -> ScreenResult:
        day = (await resolve_market_day(transaction)).last_complete_day
        if day is None:
            return ScreenResult(None, 0, screen.page, (), None)
        await transaction.execute(
            text("select set_config('statement_timeout', :timeout, true)"),
            {"timeout": QUERY_TIMEOUT},
        )
        sql, values = statement(screen)
        try:
            found = (await transaction.execute(sql, values | {"day": day})).all()
            excluding = None if found[0].matched else await explain(transaction, screen, day)
        except OperationalError as error:
            if isinstance(error.orig, QueryCanceled):
                raise ScreenTimedOut from error
            raise
        rows = tuple(dict(row._mapping) for row in found if row.isin is not None)
        return ScreenResult(day, found[0].matched, screen.page, rows, excluding)

    return await read_marts(database, read)


async def explain(transaction: AsyncSession, screen: Screen, day: date) -> Strictest | None:
    """The strictest criterion of a screen nothing passed on the day."""
    sql, values = rest_statement(screen)
    counts = (await transaction.execute(sql, values | {"day": day})).one()
    return strictest(screen, counts[0], list(counts[1:]))
