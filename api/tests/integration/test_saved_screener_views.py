"""A person's saved screens through the API."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
RISING = "gate=adtv_20d:gte:250000000&c=return_3m:gt:0&c=delivery_pct_20d:gt:50&sort=return_3m:desc"


class Person:
    """Requests to the API as one signed-in person."""

    def __init__(self, start_api: StartApi, settings: ApiSettings, headers: dict[str, str]):
        self.start_api, self.settings, self.headers = start_api, settings, headers | SAME_ORIGIN

    async def send(self, method: str, path: str, body: Any = None) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.request(method, path, json=body, headers=self.headers)

    async def save(self, name: str, query: str = RISING) -> httpx.Response:
        return await self.send("POST", "/screener/views", {"name": name, "query": query})

    async def names(self) -> list[str]:
        return [view["name"] for view in (await self.send("GET", "/screener/views")).json()]


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


async def test_a_view_keeps_its_screen_in_a_fixed_order_and_views_list_by_name(
    asha: Person,
) -> None:
    saved = await asha.save(
        "  Rising with delivery ",
        "sort=return_3m:desc&c=return_3m:gt:0&page=3&kind=companies"
        "&gate=adtv_20d:gte:250000000&c=delivery_pct_20d:gt:50",
    )

    assert saved.status_code == 201
    assert (saved.json()["name"], saved.json()["query"]) == ("Rising with delivery", RISING)
    assert (await asha.save("near 52-week high", "kind=all")).json()["query"] == "kind=all"
    assert (await asha.save("Default screen", "")).json()["query"] == ""
    assert await asha.names() == ["Default screen", "near 52-week high", "Rising with delivery"]


@pytest.mark.parametrize(
    ("query", "reason", "part"),
    [
        ("c=price_to_book:gt:3", "unknown_figure", "price_to_book:gt:3"),
        ("colour=red", "unknown_parameter", "colour"),
        ("sort=return_1d:asc&sort=return_3m:asc", "repeated_parameter", "sort"),
        ("kind=funds", "unknown_kind", "funds"),
    ],
)
async def test_a_screen_the_screener_refuses_is_not_saved(
    asha: Person, query: str, reason: str, part: str
) -> None:
    refused = await asha.save("Broken", query)

    assert (refused.status_code, refused.json()["detail"]) == (
        422,
        {"reason": reason, "part": part},
    )
    assert await asha.names() == []


async def test_a_name_is_kept_once_per_person_whatever_its_case(asha: Person, ravi: Person) -> None:
    await asha.save("Rising with delivery")

    taken = await asha.save("rising WITH delivery")

    assert (taken.status_code, taken.json()["detail"]) == (409, {"reason": "view_name_taken"})
    assert (await ravi.save("Rising with delivery")).status_code == 201


async def test_a_person_s_views_are_invisible_and_unchangeable_to_another(
    asha: Person, ravi: Person
) -> None:
    rising = (await asha.save("Rising with delivery")).json()["id"]

    renamed = await ravi.send("PATCH", f"/screener/views/{rising}", {"name": "Taken"})
    removed = await ravi.send("DELETE", f"/screener/views/{rising}")

    assert await ravi.names() == []
    assert (renamed.status_code, removed.status_code) == (404, 404)
    assert renamed.json()["detail"] == {"reason": "view_not_found"}
    assert await asha.names() == ["Rising with delivery"]


async def test_a_view_is_saved_over_and_renamed(asha: Person) -> None:
    rising = (await asha.save("Rising with delivery")).json()

    over = await asha.send("PATCH", f"/screener/views/{rising['id']}", {"query": "c=rsi_14:lt:70"})
    renamed = await asha.send(
        "PATCH", f"/screener/views/{rising['id']}", {"name": "Not overbought"}
    )

    assert over.json()["query"] == "c=rsi_14:lt:70"
    assert (renamed.json()["name"], renamed.json()["query"]) == ("Not overbought", "c=rsi_14:lt:70")
    assert renamed.json()["updated_at"] > rising["updated_at"]


async def test_a_removed_view_leaves_the_list_and_frees_its_name(asha: Person) -> None:
    rising = (await asha.save("Rising with delivery")).json()["id"]

    removed = await asha.send("DELETE", f"/screener/views/{rising}")
    again = await asha.send("DELETE", f"/screener/views/{rising}")

    assert (removed.status_code, again.status_code) == (204, 404)
    assert await asha.names() == []
    assert (await asha.save("Rising with delivery")).status_code == 201
