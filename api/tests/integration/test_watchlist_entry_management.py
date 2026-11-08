"""The instruments a person's watchlists follow, through the API, over the seed dataset."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest

from api.config import ApiSettings
from api.services import watchlist_management

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
HDFC_BANK = "INE040A01034"
INFOSYS = "INE009A01021"
KP_GREEN = "INE0QVH01025"
BAJAJ_FINANCE_BEFORE_SPLIT = "INE296A01024"


class Person:
    """Requests to the API as one signed-in person of the seed dataset, new to each test."""

    def __init__(self, start_api: StartApi, settings: ApiSettings, headers: dict[str, str]):
        self.start_api, self.settings, self.headers = start_api, settings, headers | SAME_ORIGIN

    async def send(self, method: str, path: str, body: Any = None) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.request(method, path, json=body, headers=self.headers)

    async def follow(self, isin: str, **asked: Any) -> httpx.Response:
        return await self.send("POST", "/watchlists/entries", {"isin": isin, **asked})

    async def followed(self) -> dict[str, list[tuple[str, str]]]:
        kept = (await self.send("GET", "/watchlists")).json()
        return {
            watchlist["name"]: [(entry["isin"], entry["venue"]) for entry in watchlist["entries"]]
            for watchlist in kept
        }


def refusal(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["reason"]


@pytest.fixture
def asha(
    start_api: StartApi,
    dataset_settings: ApiSettings,
    new_dataset_member: Callable[[], dict[str, str]],
) -> Person:
    return Person(start_api, dataset_settings, new_dataset_member())


@pytest.fixture
def ravi(
    start_api: StartApi,
    dataset_settings: ApiSettings,
    new_dataset_member: Callable[[], dict[str, str]],
) -> Person:
    return Person(start_api, dataset_settings, new_dataset_member())


async def test_a_first_entry_gains_a_default_list_and_follows_the_primary_venue(
    asha: Person,
) -> None:
    primary = (await asha.send("GET", f"/instruments/{HDFC_BANK}")).json()["primary_venue"]

    added = await asha.follow(HDFC_BANK)
    on_bse = await asha.follow(INFOSYS, venue="BSE")

    assert primary in ("BSE", "NSE")
    assert (added.status_code, added.json()["venue"], on_bse.json()["venue"]) == (
        201,
        primary,
        "BSE",
    )
    assert await asha.followed() == {"Watchlist": [(HDFC_BANK, primary), (INFOSYS, "BSE")]}


async def test_an_entry_follows_only_an_instrument_and_venue_listed_now(asha: Person) -> None:
    elsewhere = await asha.follow(KP_GREEN, venue="NSE")
    alone = await asha.follow(KP_GREEN)
    replaced = await asha.follow(BAJAJ_FINANCE_BEFORE_SPLIT)

    assert refusal(elsewhere) == (422, "venue_not_listed")
    assert alone.json()["venue"] == "BSE"
    assert refusal(replaced) == (422, "instrument_not_listed")


async def test_an_instrument_is_followed_once_in_a_list_and_again_in_another(asha: Person) -> None:
    await asha.follow(HDFC_BANK, venue="NSE")
    banks = (await asha.send("POST", "/watchlists", {"name": "Banks"})).json()["id"]

    again = await asha.follow(HDFC_BANK, venue="BSE")
    other = await asha.follow(HDFC_BANK, venue="BSE", watchlist_id=banks)

    assert (again.status_code, other.status_code) == (409, 201)
    assert await asha.followed() == {
        "Watchlist": [(HDFC_BANK, "NSE")],
        "Banks": [(HDFC_BANK, "BSE")],
    }


async def test_a_removed_list_ends_every_entry_it_holds(asha: Person) -> None:
    watchlist = (await asha.follow(HDFC_BANK)).json()["watchlist_id"]
    await asha.follow(INFOSYS)

    await asha.send("DELETE", f"/watchlists/{watchlist}")
    gained = (await asha.follow(INFOSYS)).json()

    assert gained["watchlist_id"] != watchlist
    assert await asha.followed() == {"Watchlist": [(INFOSYS, gained["venue"])]}


async def test_a_person_s_entries_are_invisible_and_their_lists_closed_to_another(
    asha: Person, ravi: Person
) -> None:
    kept = (await asha.follow(HDFC_BANK)).json()

    planted = await ravi.follow(INFOSYS, watchlist_id=kept["watchlist_id"])

    assert await ravi.followed() == {}
    assert refusal(planted) == (404, "watchlist_not_found")
    assert (await asha.followed())["Watchlist"] == [(HDFC_BANK, kept["venue"])]


async def test_a_list_follows_at_most_its_limit_of_instruments(
    asha: Person, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watchlist_management, "ENTRY_LIMIT", 2)
    await asha.follow(HDFC_BANK)
    await asha.follow(INFOSYS)

    refused = await asha.follow(KP_GREEN)

    assert refusal(refused) == (422, "entry_limit_reached")
