"""The instruments a person's watchlists follow, through the API, over the seed dataset."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from api.services import watchlist_management
from fixtures.database import SEED_SCHEMA

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


async def test_a_change_of_venue_ends_the_entry_and_starts_another(asha: Person) -> None:
    kept = (await asha.follow(HDFC_BANK, venue="NSE")).json()
    alone = (await asha.follow(KP_GREEN)).json()["id"]

    changed = await asha.send("PATCH", f"/watchlists/entries/{kept['id']}", {"venue": "BSE"})
    moved = changed.json()["id"]
    unchanged = await asha.send("PATCH", f"/watchlists/entries/{moved}", {"venue": "BSE"})
    ended = await asha.send("PATCH", f"/watchlists/entries/{kept['id']}", {"venue": "NSE"})
    unlisted = await asha.send("PATCH", f"/watchlists/entries/{alone}", {"venue": "NSE"})

    assert (changed.status_code, changed.json()["venue"]) == (200, "BSE")
    assert moved != kept["id"]
    assert unchanged.json() == changed.json()
    assert refusal(ended) == (404, "entry_not_found")
    assert refusal(unlisted) == (422, "venue_not_listed")
    assert await asha.followed() == {"Watchlist": [(KP_GREEN, "BSE"), (HDFC_BANK, "BSE")]}


async def test_a_removed_entry_ends_and_its_instrument_can_be_followed_again(
    asha: Person,
) -> None:
    kept = (await asha.follow(HDFC_BANK)).json()["id"]

    removed = await asha.send("DELETE", f"/watchlists/entries/{kept}")
    again = await asha.send("DELETE", f"/watchlists/entries/{kept}")

    assert (removed.status_code, refusal(again)) == (204, (404, "entry_not_found"))
    assert await asha.followed() == {"Watchlist": []}
    assert (await asha.follow(HDFC_BANK)).status_code == 201


async def test_a_person_s_entries_are_unchangeable_to_another(asha: Person, ravi: Person) -> None:
    kept = (await asha.follow(HDFC_BANK, venue="NSE")).json()["id"]

    changed = await ravi.send("PATCH", f"/watchlists/entries/{kept}", {"venue": "BSE"})
    removed = await ravi.send("DELETE", f"/watchlists/entries/{kept}")

    assert refusal(changed) == refusal(removed) == (404, "entry_not_found")
    assert await asha.followed() == {"Watchlist": [(HDFC_BANK, "NSE")]}


async def alert_on(person: Person, entry: int, rule: str, threshold: float) -> httpx.Response:
    return await person.send(
        "PUT", f"/watchlists/entries/{entry}/alert", {"rule": rule, "threshold": threshold}
    )


async def alerts(person: Person) -> list[tuple[str, str, float] | None]:
    kept = (await person.send("GET", "/watchlists")).json()
    return [
        entry["alert"] and (entry["isin"], entry["alert"]["rule"], entry["alert"]["threshold"])
        for watchlist in kept
        for entry in watchlist["entries"]
    ]


async def test_an_entry_holds_one_alert_and_a_changed_rule_replaces_it(asha: Person) -> None:
    entry = (await asha.follow(HDFC_BANK)).json()["id"]

    moving = await alert_on(asha, entry, "move_beyond", 0.02)
    same = await alert_on(asha, entry, "move_beyond", 0.02)
    above = await alert_on(asha, entry, "close_above", 1050)

    assert moving.status_code == 200
    assert same.json() == moving.json()
    assert above.json()["id"] != moving.json()["id"]
    assert await alerts(asha) == [(HDFC_BANK, "close_above", 1050.0)]


async def test_an_alert_moves_with_its_entry_to_another_venue(asha: Person) -> None:
    entry = (await asha.follow(HDFC_BANK, venue="NSE")).json()["id"]
    alert = (await alert_on(asha, entry, "delivery_above", 60)).json()

    moved = (await asha.send("PATCH", f"/watchlists/entries/{entry}", {"venue": "BSE"})).json()

    assert (moved["alert"]["rule"], moved["alert"]["threshold"]) == ("delivery_above", 60.0)
    assert moved["alert"]["id"] != alert["id"]
    assert await alerts(asha) == [(HDFC_BANK, "delivery_above", 60.0)]


async def test_a_removed_alert_leaves_its_entry_watching_nothing(asha: Person) -> None:
    entry = (await asha.follow(HDFC_BANK)).json()["id"]
    await alert_on(asha, entry, "spread_above", 300)

    removed = await asha.send("DELETE", f"/watchlists/entries/{entry}/alert")
    again = await asha.send("DELETE", f"/watchlists/entries/{entry}/alert")

    assert (removed.status_code, refusal(again)) == (204, (404, "alert_not_found"))
    assert await alerts(asha) == [None]


async def test_ending_an_entry_or_its_list_ends_its_alert(
    asha: Person, seeded_postgres: str
) -> None:
    removed = (await asha.follow(HDFC_BANK)).json()
    listed = (await asha.follow(INFOSYS)).json()
    set_alerts = [
        (await alert_on(asha, entry, "close_below", 900)).status_code
        for entry in (removed["id"], listed["id"])
    ]

    await asha.send("DELETE", f"/watchlists/entries/{removed['id']}")
    await asha.send("DELETE", f"/watchlists/{listed['watchlist_id']}")

    with psycopg.connect(seeded_postgres, options=f"-csearch_path={SEED_SCHEMA}") as owner:
        open_alerts = owner.execute(
            "select count(*) from watchlist_alert where ended_at is null and entry_id = any(%s)",
            ([removed["id"], listed["id"]],),
        ).fetchone()
    assert (set_alerts, open_alerts) == ([200, 200], (0,))


@pytest.mark.parametrize(
    ("rule", "threshold"),
    [("move_beyond", 0), ("spread_above", -5), ("delivery_below", 100), ("price_above", 900)],
)
async def test_an_alert_holds_a_known_rule_and_a_threshold_it_can_cross(
    asha: Person, rule: str, threshold: float
) -> None:
    entry = (await asha.follow(HDFC_BANK)).json()["id"]

    assert (await alert_on(asha, entry, rule, threshold)).status_code == 422
    assert await alerts(asha) == [None]


async def test_a_person_s_alerts_are_unchangeable_to_another(asha: Person, ravi: Person) -> None:
    entry = (await asha.follow(HDFC_BANK)).json()["id"]
    await alert_on(asha, entry, "move_beyond", 0.02)

    changed = await alert_on(ravi, entry, "move_beyond", 0.5)
    removed = await ravi.send("DELETE", f"/watchlists/entries/{entry}/alert")

    assert refusal(changed) == refusal(removed) == (404, "entry_not_found")
    assert await alerts(asha) == [(HDFC_BANK, "move_beyond", 0.02)]
