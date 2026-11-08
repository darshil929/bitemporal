"""A person's watchlists through the API."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


class Person:
    """Requests to the API as one signed-in person."""

    def __init__(self, start_api: StartApi, settings: ApiSettings, headers: dict[str, str]):
        self.start_api, self.settings, self.headers = start_api, settings, headers | SAME_ORIGIN

    async def send(self, method: str, path: str, body: Any = None) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.request(method, path, json=body, headers=self.headers)

    async def add(self, name: str) -> httpx.Response:
        return await self.send("POST", "/watchlists", {"name": name})

    async def lists(self) -> list[tuple[str, bool]]:
        kept = (await self.send("GET", "/watchlists")).json()
        return [(watchlist["name"], watchlist["is_default"]) for watchlist in kept]


@pytest.fixture
def asha(
    start_api: StartApi, migrated_settings: ApiSettings, member_headers: dict[str, str]
) -> Person:
    return Person(start_api, migrated_settings, member_headers)


@pytest.fixture
def ravi(
    start_api: StartApi, migrated_settings: ApiSettings, other_member_headers: dict[str, str]
) -> Person:
    return Person(start_api, migrated_settings, other_member_headers)


async def test_the_earliest_list_is_the_default_and_the_rest_list_by_name(asha: Person) -> None:
    added = await asha.add("  Watchlist ")
    await asha.add("private banks")
    await asha.add("IT services")

    assert added.status_code == 201
    assert (added.json()["name"], added.json()["is_default"]) == ("Watchlist", True)
    assert await asha.lists() == [
        ("Watchlist", True),
        ("IT services", False),
        ("private banks", False),
    ]


async def test_a_list_name_is_kept_once_per_person_whatever_its_case(
    asha: Person, ravi: Person
) -> None:
    await asha.add("Private banks")
    banks = (await asha.add("IT services")).json()["id"]

    taken = await asha.add("PRIVATE banks")
    renamed = await asha.send("PATCH", f"/watchlists/{banks}", {"name": "private BANKS"})

    assert (taken.status_code, taken.json()["detail"]) == (409, {"reason": "watchlist_name_taken"})
    assert renamed.status_code == 409
    assert (await ravi.add("Private banks")).status_code == 201


async def test_a_person_s_lists_are_invisible_and_unchangeable_to_another(
    asha: Person, ravi: Person
) -> None:
    banks = (await asha.add("Private banks")).json()["id"]

    renamed = await ravi.send("PATCH", f"/watchlists/{banks}", {"name": "Taken"})
    removed = await ravi.send("DELETE", f"/watchlists/{banks}")

    assert await ravi.lists() == []
    assert (renamed.status_code, removed.status_code) == (404, 404)
    assert renamed.json()["detail"] == {"reason": "watchlist_not_found"}
    assert await asha.lists() == [("Private banks", True)]


async def test_a_renamed_list_keeps_its_place_as_the_default(asha: Person) -> None:
    first = (await asha.add("Watchlist")).json()
    await asha.add("IT services")

    renamed = await asha.send("PATCH", f"/watchlists/{first['id']}", {"name": "Zinc and steel"})

    assert (renamed.json()["name"], renamed.json()["is_default"]) == ("Zinc and steel", True)
    assert renamed.json()["updated_at"] > first["updated_at"]
    assert await asha.lists() == [("Zinc and steel", True), ("IT services", False)]


async def test_a_removed_list_frees_its_name_and_passes_the_default_on(asha: Person) -> None:
    first = (await asha.add("Watchlist")).json()["id"]
    await asha.add("IT services")

    removed = await asha.send("DELETE", f"/watchlists/{first}")
    again = await asha.send("DELETE", f"/watchlists/{first}")

    assert (removed.status_code, again.status_code) == (204, 404)
    assert await asha.lists() == [("IT services", True)]
    assert (await asha.add("Watchlist")).status_code == 201


async def test_a_person_keeps_at_most_twenty_lists(asha: Person) -> None:
    kept = [(await asha.add(f"List {number:02}")).json()["id"] for number in range(20)]

    refused = await asha.add("List 21")
    await asha.send("DELETE", f"/watchlists/{kept[0]}")

    assert (refused.status_code, refused.json()["detail"]) == (
        422,
        {"reason": "watchlist_limit_reached"},
    )
    assert (await asha.add("List 21")).status_code == 201


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
async def test_a_list_name_is_one_to_eighty_characters_once_trimmed(
    asha: Person, name: str
) -> None:
    assert (await asha.add(name)).status_code == 422
    assert await asha.lists() == []
