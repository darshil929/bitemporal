"""Screens of the daily features, read over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import date
from typing import Any, cast

import httpx
import psycopg
import pytest
from sqlalchemy import text

from api.config import ApiSettings
from api.services import screener_queries

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
Screener = Callable[..., Awaitable[httpx.Response]]

LAST_COMPLETE_DAY = (
    "select trade_date from mart_trading_days group by trade_date having bool_and(is_complete)"
    " order by trade_date desc limit 1"
)
PASSING = (
    "select isin from mart_daily_features where trade_date = %s and adtv_20d >= 250000000"
    " and isin like 'INE%%' {extra} order by {order} nulls last, isin"
)
SCREENED = (
    "select count(*) from mart_daily_features inner join mart_instruments using (isin)"
    " where trade_date = %s and isin like 'INE%%' {extra}"
)
BARS = (
    "select trade_date, close from mart_adjusted_prices where isin = %s and venue = %s"
    " and trade_date <= %s order by trade_date"
)
UNHANDLED = (
    "select ex_date, purpose from mart_corporate_actions where isin = %s"
    " and action_type = 'unhandled' and ex_date > %s and ex_date <= %s"
    " order by ex_date desc, purpose"
)


@pytest.fixture
def screener(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Screener:
    async def screening(*query: tuple[str, str], signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get("/screener", params=list(query), headers=headers)

    return screening


def screened_day(models: psycopg.Connection) -> date:
    day = models.execute(LAST_COMPLETE_DAY).fetchone()
    assert day is not None
    return cast(date, day[0])


def passing(models: psycopg.Connection, extra: str = "", order: str = "adtv_20d desc") -> list[str]:
    query = PASSING.format(extra=extra, order=order)
    return [isin for (isin,) in models.execute(query, (screened_day(models),))]


def screened(models: psycopg.Connection, extra: str = "") -> int:
    count = models.execute(SCREENED.format(extra=extra), (screened_day(models),)).fetchone()
    assert count is not None
    return cast(int, count[0])


def row_detail(models: psycopg.Connection, row: dict[str, Any], lookback: int) -> dict[str, Any]:
    """A row's trend, and the unhandled actions after the earliest of the bars its figures read."""
    day = screened_day(models)
    bars = models.execute(BARS, (row["isin"], row["primary_venue"], day)).fetchall()
    closes = [float(close) for _, close in bars if close is not None]
    first_day = bars[-(lookback + 1)][0] if len(bars) > lookback else bars[0][0]
    actions = models.execute(UNHANDLED, (row["isin"], first_day, day)).fetchall()
    trend_bars = screener_queries.TREND_BARS
    return {
        "trend_3m": closes[-trend_bars:] if len(closes) >= trend_bars else None,
        "unhandled_actions": [
            {"ex_date": ex_date.isoformat(), "purpose": purpose} for ex_date, purpose in actions
        ],
    }


def shown_detail(row: dict[str, Any]) -> dict[str, Any]:
    return {"trend_3m": row["trend_3m"], "unhandled_actions": row["unhandled_actions"]}


async def test_a_screen_holds_companies_past_the_gate_most_traded_first(
    screener: Screener, seeded_models: psycopg.Connection
) -> None:
    body = (await screener()).json()

    expected = passing(seeded_models)
    assert expected
    assert [row["isin"] for row in body["rows"]] == expected
    assert body["matched"] == len(expected)
    assert all(row["figures"]["adtv_20d"] >= 250_000_000 for row in body["rows"])
    assert body["rows"][0]["symbol"]
    assert body["strictest"] is None


async def test_a_named_sort_orders_the_screen(
    screener: Screener, seeded_models: psycopg.Connection
) -> None:
    body = (await screener(("sort", "return_3m:asc"))).json()

    assert [row["isin"] for row in body["rows"]] == passing(seeded_models, order="return_3m asc")
    assert {"adtv_20d", "return_3m"} <= set(body["rows"][0]["figures"])


async def test_each_criterion_narrows_the_screen_and_shows_its_figure(
    screener: Screener, seeded_models: psycopg.Connection
) -> None:
    body = (
        await screener(
            ("c", "return_3m:gt:0"), ("c", "is_52w_high:eq:false"), ("sort", "return_3m:asc")
        )
    ).json()

    expected = passing(seeded_models, "and return_3m > 0 and is_52w_high = false", "return_3m asc")
    assert [row["isin"] for row in body["rows"]] == expected
    assert all(row["figures"]["return_3m"] > 0 for row in body["rows"])
    assert {row["figures"]["is_52w_high"] for row in body["rows"]} == {False}


async def test_without_the_gate_instruments_below_it_pass(screener: Screener) -> None:
    gated = (await screener()).json()
    ungated = (await screener(("gate", "none"), ("kind", "all"))).json()

    assert ungated["matched"] > gated["matched"]
    assert any(row["figures"]["adtv_20d"] < 250_000_000 for row in ungated["rows"])


async def test_rows_below_the_gate_are_marked_whatever_gate_the_screen_sets(
    screener: Screener,
) -> None:
    for gate in ("none", "adtv_20d:gte:1"):
        rows = (await screener(("gate", gate), ("sort", "adtv_20d:asc"))).json()["rows"]

        assert any(row["is_below_gate"] for row in rows)
        assert any(row["is_below_gate"] is False for row in rows)
        for row in rows:
            traded = row["figures"]["adtv_20d"]
            assert row["is_below_gate"] == (None if traded is None else traded < 250_000_000)


async def test_an_empty_screen_names_the_criterion_excluding_the_rest(
    screener: Screener, seeded_models: psycopg.Connection
) -> None:
    body = (await screener(("c", "return_3m:gt:0"), ("c", "return_1d:gt:10"))).json()

    rest = passing(seeded_models, "and return_3m > 0")
    assert rest
    assert (body["matched"], body["rows"]) == (0, [])
    assert body["strictest"] == {
        "criterion": "return_1d:gt:10",
        "is_gate": False,
        "passing_the_rest": len(rest),
        "screened": screened(seeded_models),
    }


async def test_the_gate_is_named_where_it_alone_empties_a_screen(
    screener: Screener, seeded_models: psycopg.Connection
) -> None:
    body = (await screener(("gate", "adtv_20d:gte:1e15"), ("c", "return_1d:gt:-1"))).json()

    assert body["matched"] == 0
    assert body["strictest"] == {
        "criterion": "adtv_20d:gte:1e15",
        "is_gate": True,
        "passing_the_rest": screened(seeded_models, "and return_1d > -1"),
        "screened": screened(seeded_models),
    }


def test_the_strictest_criterion_is_one_of_the_screen_before_the_gate() -> None:
    screen = screener_queries.screen_from(
        None, "companies", ["return_3m:gt:0", "delivery_pct_20d:gt:80"], None, 1
    )

    found = screener_queries.strictest(screen, 4987, [714, 0, 242])
    tied = screener_queries.strictest(screen, 4987, [714, 30, 30])

    assert found is not None and tied is not None
    assert (found.criterion.part, found.is_gate, found.passing_the_rest) == (
        "delivery_pct_20d:gt:80",
        False,
        242,
    )
    assert tied.criterion.part == "return_3m:gt:0"
    assert screener_queries.strictest(screen, 4987, [0, 0, 0]) is None


async def test_each_row_carries_its_trend_and_the_unhandled_actions_its_figures_span(
    screener: Screener, seeded_models: psycopg.Connection
) -> None:
    rows = (await screener()).json()["rows"]

    assert [shown_detail(row) for row in rows] == [
        row_detail(seeded_models, row, screener_queries.TREND_BARS - 1) for row in rows
    ]
    assert all(row["trend_3m"] for row in rows)
    assert any(row["unhandled_actions"] for row in rows)


async def test_a_figure_reaching_further_back_widens_the_actions_listed(
    screener: Screener, seeded_models: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screener_queries, "TREND_BARS", 40)

    short = (await screener()).json()["rows"]
    long = (await screener(("sort", "return_1y:desc"))).json()["rows"]

    assert [shown_detail(row) for row in short] == [
        row_detail(seeded_models, row, 39) for row in short
    ]
    assert [shown_detail(row) for row in long] == [
        row_detail(seeded_models, row, 252) for row in long
    ]
    listed = sum(len(row["unhandled_actions"]) for row in short)
    assert sum(len(row["unhandled_actions"]) for row in long) > listed > 0


async def test_a_row_with_fewer_bars_than_its_trend_shows_none(
    screener: Screener, seeded_models: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screener_queries, "TREND_BARS", 300)

    rows = (await screener(("gate", "none"))).json()["rows"]

    assert [shown_detail(row) for row in rows] == [
        row_detail(seeded_models, row, 299) for row in rows
    ]
    assert {row["trend_3m"] is None for row in rows} == {True, False}


async def test_pages_stop_at_the_row_cap(
    screener: Screener, seeded_models: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screener_queries, "PAGE_SIZE", 3)
    monkeypatch.setattr(screener_queries, "ROW_CAP", 5)

    second = (await screener(("page", "2"))).json()

    assert [row["isin"] for row in second["rows"]] == passing(seeded_models)[3:5]
    assert second["matched"] == len(passing(seeded_models))


@pytest.mark.parametrize(
    ("name", "value", "reason"),
    [
        ("gate", "adtv_20d:gte", "malformed_criterion"),
        ("gate", "price_to_book:gt:3", "unknown_figure"),
        ("gate", "adtv_20d:above:0", "unknown_comparison"),
        ("gate", "adtv_20d:gte:many", "malformed_value"),
        ("gate", "return_1d:gt:0", "malformed_gate"),
        ("sort", "close:desc", "unknown_sort"),
        ("c", "price_to_book:gt:3", "unknown_figure"),
        ("c", "is_52w_high:gt:1", "malformed_criterion"),
    ],
)
async def test_a_screen_naming_what_it_may_not_use_is_refused(
    screener: Screener, name: str, value: str, reason: str
) -> None:
    response = await screener((name, value))

    assert response.status_code == 422
    assert response.json()["detail"] == {"reason": reason, "part": value}


async def test_a_screen_running_past_the_time_limit_shows_nothing(
    screener: Screener, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screener_queries, "QUERY_TIMEOUT", "50ms")
    slow = text("select pg_sleep(1) where cast(:day as date) is not null")
    monkeypatch.setattr(screener_queries, "statement", lambda screen: (slow, {}))

    response = await screener()

    assert response.status_code == 503
    assert response.json() == {"detail": {"reason": "screener_query_timed_out"}}


async def test_screens_are_refused_without_a_session(screener: Screener) -> None:
    assert (await screener(signed_in=False)).status_code == 401
