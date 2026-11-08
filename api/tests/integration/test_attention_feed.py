"""The needs-attention feed through the API, over the seed dataset."""

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from fixtures.database import SEED_SCHEMA

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
HDFC_BANK = "INE040A01034"
BAJAJ_FINANCE_BEFORE_SPLIT = "INE296A01024"


class Person:
    """Requests to the API as one signed-in person of the seed dataset, new to each test."""

    def __init__(self, start_api: StartApi, settings: ApiSettings, headers: dict[str, str]):
        self.start_api, self.settings, self.headers = start_api, settings, headers | SAME_ORIGIN

    async def send(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        async with self.start_api(self.settings) as api:
            answered = await api.request(method, path, json=body, headers=self.headers)
        assert answered.status_code < 300
        return dict(answered.json())


@pytest.fixture
def people(
    start_api: StartApi,
    dataset_settings: ApiSettings,
    new_dataset_member: Callable[[], dict[str, str]],
) -> Callable[[], Person]:
    return lambda: Person(start_api, dataset_settings, new_dataset_member())


@pytest.fixture
def owner(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        seeded_postgres, options=f"-csearch_path={SEED_SCHEMA},public", autocommit=True
    ) as connection:
        yield connection


async def test_a_triggered_alert_and_a_replaced_isin_need_attention(
    people: Callable[[], Person], owner: psycopg.Connection
) -> None:
    asha, ravi = people(), people()
    entry = await asha.send("POST", "/watchlists/entries", {"isin": HDFC_BANK, "venue": "NSE"})
    alert = await asha.send(
        "PUT",
        f"/watchlists/entries/{entry['id']}/alert",
        {"rule": "move_beyond", "threshold": 0.0002},
    )
    owner.execute(
        "insert into watchlist_alert_evaluation"
        " (owner_id, alert_id, trade_date, as_of_date, status, figure)"
        " select owner_id, id, '2025-12-31', '2025-12-31', 'triggered', 0.0003"
        " from watchlist_alert where id = %s",
        (alert["id"],),
    )
    owner.execute(
        "insert into watchlist_entry (owner_id, watchlist_id, isin, venue)"
        " select owner_id, id, %s, 'NSE' from watchlist where id = %s",
        (BAJAJ_FINANCE_BEFORE_SPLIT, entry["watchlist_id"]),
    )

    found = await asha.send("GET", "/attention")
    other = await ravi.send("GET", "/attention")

    assert found["published_day"] == "2025-12-31"
    assert [(item["isin"], item["figure"]) for item in found["alerts"]] == [(HDFC_BANK, 0.0003)]
    assert [item["isin"] for item in found["superseded"]] == [BAJAJ_FINANCE_BEFORE_SPLIT]
    assert (other["alerts"], other["superseded"]) == ([], [])


async def test_nothing_needs_attention_on_a_quiet_day(
    people: Callable[[], Person],
) -> None:
    asha = people()
    await asha.send("POST", "/watchlists/entries", {"isin": HDFC_BANK})

    found = await asha.send("GET", "/attention")

    assert {kind: found[kind] for kind in found if kind != "published_day"} == {
        "alerts": [],
        "superseded": [],
    }
