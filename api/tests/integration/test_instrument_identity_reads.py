"""Each instrument's names, listings, open venues and primary venue, read over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
Read = Callable[..., Awaitable[httpx.Response]]

HDFC_BANK = "INE040A01034"
SPICEJET = "INE285B01017"
BAJAJ_FINANCE_BEFORE_ITS_SPLIT = "INE296A01024"
BAJAJ_FINANCE = "INE296A01032"

NEWEST_VENUE = (
    "select primary_venue from mart_daily_features where isin = %s order by trade_date desc limit 1"
)


def stretch(exchange: str, symbol: str, scrip_code: str | None, **closed: str) -> dict[str, Any]:
    return {
        "exchange": exchange,
        "local_symbol": symbol,
        "scrip_code": scrip_code,
        "listing_date": closed.get("listing_date", "2024-01-01"),
        "delisting_date": closed.get("delisting_date"),
        "closure_reason": closed.get("closure_reason"),
    }


@pytest.fixture
def read(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Read:
    async def reading(isin: str, signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get(f"/instruments/{isin}", headers=headers)

    return reading


async def test_a_dual_listed_instrument_opens_on_its_newest_feature_venue(
    read: Read, seeded_models: psycopg.Connection
) -> None:
    newest_venue = seeded_models.execute(NEWEST_VENUE, (HDFC_BANK,)).fetchone()

    response = await read(HDFC_BANK)

    body = response.json()
    assert response.status_code == 200
    assert newest_venue is not None
    assert (body["primary_venue"], body["superseded_by"]) == (newest_venue[0], None)
    assert (body["venues"], body["is_single_listed"]) == (["BSE", "NSE"], False)
    assert body["listings"] == [
        stretch("BSE", "HDFCBANK", "500180"),
        stretch("NSE", "HDFCBANK", None),
    ]


async def test_an_instrument_one_venue_lists_is_single_listed(read: Read) -> None:
    body = (await read(SPICEJET)).json()

    assert (body["venues"], body["is_single_listed"]) == (["BSE"], True)
    assert body["listings"] == [stretch("BSE", "SPICEJET", "500285")]


async def test_a_superseded_isin_names_the_isin_that_took_it_over(read: Read) -> None:
    body = (await read(BAJAJ_FINANCE_BEFORE_ITS_SPLIT)).json()

    closed = {"delisting_date": "2025-06-13", "closure_reason": "superseded"}
    assert body["superseded_by"] == BAJAJ_FINANCE
    assert (body["venues"], body["is_single_listed"], body["primary_venue"]) == ([], False, None)
    assert body["listings"] == [
        stretch("BSE", "BAJFINANCE", "500034", **closed),
        stretch("NSE", "BAJFINANCE", None, **closed),
    ]


async def test_an_isin_the_platform_does_not_hold_is_not_found(read: Read) -> None:
    response = await read("INE999Z01019")

    assert response.status_code == 404
    assert response.json() == {"detail": {"reason": "instrument_not_found"}}


async def test_a_malformed_isin_is_refused(read: Read) -> None:
    assert (await read("HDFCBANK")).status_code == 422


async def test_instrument_reads_are_refused_without_a_session(read: Read) -> None:
    assert (await read(HDFC_BANK, signed_in=False)).status_code == 401
