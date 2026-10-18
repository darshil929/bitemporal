"""Screens of the daily features, read over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

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


@pytest.fixture
def screener(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Screener:
    async def screening(*query: tuple[str, str], signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get("/screener", params=list(query), headers=headers)

    return screening


def passing(models: psycopg.Connection, extra: str = "", order: str = "adtv_20d desc") -> list[str]:
    day = models.execute(LAST_COMPLETE_DAY).fetchone()
    assert day is not None
    query = PASSING.format(extra=extra, order=order)
    return [isin for (isin,) in models.execute(query, (day[0],))]


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
