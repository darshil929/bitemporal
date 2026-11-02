"""Breadth across the companies that traded, read over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import date
from statistics import median

import httpx
import psycopg
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
Summary = Callable[..., Awaitable[httpx.Response]]

DAY = date(2025, 12, 31)
COMPANIES = (
    "select isin, return_1d, adtv_20d, is_52w_high, is_52w_low from mart_daily_features"
    " where trade_date = %s and isin like 'INE%%'"
)


@pytest.fixture
def summary(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Summary:
    async def read(signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get("/market/summary", headers=headers)

    return read


async def test_breadth_counts_the_companies_that_traded_on_the_day(
    summary: Summary, seeded_models: psycopg.Connection
) -> None:
    body = (await summary()).json()

    rows = seeded_models.execute(COMPANIES, (DAY,)).fetchall()
    returns = [row[1] for row in rows if row[1] is not None]
    assert body["day"] == DAY.isoformat()
    assert rows
    assert body["breadth"] == pytest.approx(
        {
            "companies": len(rows),
            "advancing": sum(1 for value in returns if value > 0),
            "declining": sum(1 for value in returns if value < 0),
            "unchanged": sum(1 for value in returns if value == 0),
            "new_52w_highs": sum(1 for row in rows if row[3]),
            "new_52w_lows": sum(1 for row in rows if row[4]),
            "median_return_1d": median(returns),
        }
    )


async def test_breadth_names_the_bhavcopies_behind_it(summary: Summary) -> None:
    body = (await summary()).json()

    assert {source["source_id"] for source in body["breadth_sources"]} == {
        "bse_bhavcopy_equity",
        "nse_bhavcopy_equity",
    }


async def test_before_the_first_publish_there_is_no_summary(
    start_api: StartApi, migrated_settings: ApiSettings, member_headers: dict[str, str]
) -> None:
    async with start_api(migrated_settings) as api:
        response = await api.get("/market/summary", headers=member_headers)

    assert (response.status_code, response.json()) == (
        200,
        {"day": None, "breadth": None, "breadth_sources": []},
    )


async def test_the_summary_is_refused_without_a_session(summary: Summary) -> None:
    assert (await summary(signed_in=False)).status_code == 401
