"""Finding instruments by part of a name, a symbol, a scrip code or an ISIN, over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
Search = Callable[..., Awaitable[httpx.Response]]

SPICEJET = "INE285B01017"
PIRAMAL_ENTERPRISES = "INE140A01024"


@pytest.fixture
def search(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Search:
    async def searching(typed: str, signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get("/instruments", params={"q": typed}, headers=headers)

    return searching


async def isins(search: Search, typed: str) -> list[str]:
    response = await search(typed)
    assert response.status_code == 200
    return [match["isin"] for match in response.json()]


async def test_instruments_listed_now_come_before_closed_ones(search: Search) -> None:
    assert await isins(search, "pi") == [SPICEJET, PIRAMAL_ENTERPRISES]


async def test_a_scrip_code_finds_its_instrument_under_its_symbol(search: Search) -> None:
    response = await search("500180")

    assert response.json() == [
        {
            "isin": "INE040A01034",
            "display_name": "HDFC BANK LTD",
            "symbol": "HDFCBANK",
            "venues": ["BSE", "NSE"],
        }
    ]


async def test_an_isin_before_a_split_finds_the_isin_that_took_it_over(search: Search) -> None:
    assert await isins(search, "INE296A01024") == ["INE296A01032"]


async def test_a_former_symbol_finds_the_instrument_under_its_symbol_now(search: Search) -> None:
    matches = (await search("zomato")).json()

    assert [(match["isin"], match["symbol"]) for match in matches] == [("INE758T01015", "ETERNAL")]


async def test_pattern_characters_are_read_as_typed(search: Search) -> None:
    assert await isins(search, "%%") == []


async def test_at_most_ten_instruments_are_found(search: Search) -> None:
    assert len(await isins(search, "IN")) == 10


async def test_a_search_shorter_than_two_characters_is_refused(search: Search) -> None:
    assert [(await search(typed)).status_code for typed in ("h", " hdfc")] == [422, 422]


async def test_search_is_refused_without_a_session(search: Search) -> None:
    assert (await search("hdfc", signed_in=False)).status_code == 401
