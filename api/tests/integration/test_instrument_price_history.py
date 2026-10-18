"""An instrument's daily series at one venue over a range, read over the seed dataset."""

import statistics
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
Prices = Callable[..., Awaitable[httpx.Response]]

HDFC_BANK = "INE040A01034"
BAJAJ_FINANCE = "INE296A01032"
BAJAJ_FINANCE_BEFORE_ITS_SPLIT = "INE296A01024"

TRADED_VOLUME = (
    "select volume from mart_price_daily where isin = %s and venue = %s and trade_date = %s"
)
FEATURE_ROWS = (
    "select trade_date::text, primary_venue, sma_50 from mart_daily_features where isin = %s"
)


@pytest.fixture
def prices(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Prices:
    async def reading(isin: str, signed_in: bool = True, **query: str) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get(f"/instruments/{isin}/prices", params=query, headers=headers)

    return reading


async def days(prices: Prices, isin: str, **query: str) -> dict[str, dict[str, Any]]:
    response = await prices(isin, **query)
    assert response.status_code == 200
    return {day["trade_date"]: day for day in response.json()["days"]}


async def test_days_before_an_action_are_scaled_by_its_factor(
    prices: Prices, seeded_models: psycopg.Connection
) -> None:
    series = await days(prices, HDFC_BANK, venue="NSE")
    before, ex_date = series["2025-08-25"], series["2025-08-26"]
    traded = seeded_models.execute(TRADED_VOLUME, (HDFC_BANK, "NSE", "2025-08-25")).fetchone()

    assert (before["adjustment_factor"], ex_date["adjustment_factor"]) == (0.5, 1.0)
    assert before["close"] == pytest.approx(before["close_as_traded"] * 0.5)
    assert ex_date["close"] == ex_date["close_as_traded"]
    assert traded is not None
    assert before["volume"] == pytest.approx(traded[0] / 0.5)


@pytest.mark.parametrize("venue", ["BSE", "NSE"])
async def test_overlays_are_in_the_candle_scale_on_days_computed_on_the_venue(
    prices: Prices, seeded_models: psycopg.Connection, venue: str
) -> None:
    computed = {
        day: (on, sma) for day, on, sma in seeded_models.execute(FEATURE_ROWS, (HDFC_BANK,))
    }

    series = await days(prices, HDFC_BANK, venue=venue)

    for day, values in series.items():
        on, sma_50 = computed[day]
        if on == venue and sma_50 is not None:
            assert values["sma_50"] == pytest.approx(sma_50 * values["adjustment_factor"]), day
        else:
            assert values["sma_50"] is None, day


async def test_a_single_listed_instrument_has_no_other_venue_or_spread(prices: Prices) -> None:
    series = await days(prices, "INE285B01017", venue="BSE", range="1Y")

    assert series
    assert {(day["other_venue_close"], day["venue_spread_bps"]) for day in series.values()} == {
        (None, None)
    }


async def test_the_median_spread_is_taken_over_the_days_returned(prices: Prices) -> None:
    dual = (await prices(HDFC_BANK, venue="NSE")).json()
    single = (await prices("INE285B01017", venue="BSE", range="1Y")).json()

    spreads = [day["venue_spread_bps"] for day in dual["days"]]
    assert None not in spreads
    assert dual["venue_spread_median_bps"] == pytest.approx(statistics.median(spreads))
    assert single["venue_spread_median_bps"] is None


async def test_the_spread_reaches_days_published_under_a_replaced_isin(prices: Prices) -> None:
    series = await days(prices, BAJAJ_FINANCE, venue="NSE", range="1Y")

    before_split = [day for date, day in series.items() if date < "2025-06-16"]
    assert before_split
    assert all(day["adjustment_factor"] == pytest.approx(0.1) for day in before_split)
    assert all(day["venue_spread_bps"] is not None for day in before_split)


async def test_a_replaced_isin_shows_its_own_days_up_to_its_change(prices: Prices) -> None:
    body = (await prices(BAJAJ_FINANCE_BEFORE_ITS_SPLIT, venue="BSE", range="All")).json()

    assert body["last_day"] == "2025-06-13"
    assert all(day["adjustment_factor"] == pytest.approx(0.1) for day in body["days"])


async def test_a_range_ends_on_the_published_day(prices: Prices) -> None:
    body = (await prices(HDFC_BANK, venue="NSE", range="1M")).json()

    assert (body["range"], body["last_day"]) == ("1M", "2025-12-31")
    assert body["first_day"] > "2025-11-30"


async def test_an_unknown_isin_is_not_found(prices: Prices) -> None:
    response = await prices("INE999Z01019", venue="NSE")

    assert response.status_code == 404
    assert response.json() == {"detail": {"reason": "instrument_not_found"}}


async def test_a_venue_or_range_outside_the_lists_is_refused(prices: Prices) -> None:
    refused = [
        await prices(HDFC_BANK, venue="LSE"),
        await prices(HDFC_BANK, venue="NSE", range="2Y"),
    ]

    assert [response.status_code for response in refused] == [422, 422]


async def test_price_reads_are_refused_without_a_session(prices: Prices) -> None:
    assert (await prices(HDFC_BANK, signed_in=False, venue="NSE")).status_code == 401
