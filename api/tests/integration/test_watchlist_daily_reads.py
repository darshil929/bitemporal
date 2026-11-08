"""A watchlist's rows through the API, over the seed dataset's published figures."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date
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
KP_GREEN = "INE0QVH01025"
BAJAJ_FINANCE_BEFORE_SPLIT = "INE296A01024"
BAJAJ_FINANCE = "INE296A01032"


class Person:
    """Requests to the API as one signed-in person of the seed dataset, new to each test."""

    def __init__(self, start_api: StartApi, settings: ApiSettings, headers: dict[str, str]):
        self.start_api, self.settings, self.headers = start_api, settings, headers | SAME_ORIGIN

    async def send(self, method: str, path: str, body: Any = None) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.request(method, path, json=body, headers=self.headers)

    async def follow(self, isin: str, **asked: Any) -> dict[str, Any]:
        added = await self.send("POST", "/watchlists/entries", {"isin": isin, **asked})
        assert added.status_code == 201
        return dict(added.json())

    async def rows(self, watchlist: int) -> dict[str, Any]:
        return dict((await self.send("GET", f"/watchlists/{watchlist}/rows")).json())


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


@pytest.fixture
def owner(seeded_postgres: str) -> Any:
    with psycopg.connect(
        seeded_postgres, options=f"-csearch_path={SEED_SCHEMA},public", autocommit=True
    ) as connection:
        yield connection


def figures(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["trade_date"],
        row["close"],
        round(row["change_1d"], 2),
        round(row["return_1d"], 5),
        round(row["return_1m"], 5),
        round(row["delivery_pct_1d"], 1),
    )


async def test_each_row_reads_the_entry_s_newest_session_at_its_venue(asha: Person) -> None:
    on_nse = await asha.follow(HDFC_BANK, venue="NSE")
    await asha.follow(KP_GREEN)
    banks = (await asha.send("POST", "/watchlists", {"name": "Banks"})).json()["id"]
    await asha.follow(HDFC_BANK, venue="BSE", watchlist_id=banks)

    listed = await asha.rows(on_nse["watchlist_id"])
    hdfc, kp_green = listed["rows"]
    on_bse = (await asha.rows(banks))["rows"][0]

    assert (listed["published_day"], listed["triggered"]) == ("2025-12-31", 0)
    assert (hdfc["display_name"], hdfc["local_symbol"], hdfc["is_stale"]) == (
        "HDFC BANK LTD",
        "HDFCBANK",
        False,
    )
    assert figures(hdfc) == ("2025-12-31", 991.2, 0.3, 0.0003, -0.01088, 64.2)
    assert figures(on_bse) == ("2025-12-31", 991.75, 1.05, 0.00106, -0.01077, 53.6)
    assert hdfc["venue_spread_bps"] == pytest.approx(5.5, abs=0.05)
    assert (kp_green["venue"], kp_green["close"], kp_green["venue_spread_bps"]) == (
        "BSE",
        440.95,
        None,
    )
    assert (len(hdfc["trend_1m"]), hdfc["trend_1m"][-1]) == (22, 991.2)
    assert [source["source_id"] for source in listed["sources"]] == [
        "nse_bhavcopy_equity",
        "nse_delivery",
        "bse_bhavcopy_equity",
        "bse_delivery",
    ]


async def test_a_replaced_isin_reads_its_last_session_and_its_successor(
    asha: Person, owner: psycopg.Connection
) -> None:
    watchlist = (await asha.follow(HDFC_BANK))["watchlist_id"]
    owner.execute(
        "insert into watchlist_entry (owner_id, watchlist_id, isin, venue)"
        " select owner_id, id, %s, 'NSE' from watchlist where id = %s",
        (BAJAJ_FINANCE_BEFORE_SPLIT, watchlist),
    )

    replaced = (await asha.rows(watchlist))["rows"][1]

    assert (replaced["trade_date"], replaced["is_stale"], replaced["superseded_by"]) == (
        "2025-06-13",
        True,
        BAJAJ_FINANCE,
    )
    assert replaced["close"] is not None
    assert len(replaced["trend_1m"]) == 22
    assert replaced["return_1d"] is not None


async def test_a_row_carries_its_alert_s_latest_verdict(
    asha: Person, owner: psycopg.Connection
) -> None:
    entry = await asha.follow(HDFC_BANK, venue="NSE")
    alert = (
        await asha.send(
            "PUT",
            f"/watchlists/entries/{entry['id']}/alert",
            {"rule": "move_beyond", "threshold": 0.0002},
        )
    ).json()
    unjudged = (await asha.rows(entry["watchlist_id"]))["rows"][0]
    for day, status, figure in (
        ("2025-12-30", "watching", -0.0001),
        ("2025-12-31", "triggered", 0.0003),
    ):
        owner.execute(
            "insert into watchlist_alert_evaluation"
            " (owner_id, alert_id, trade_date, as_of_date, status, figure)"
            " select owner_id, id, %s, %s, %s, %s from watchlist_alert where id = %s",
            (day, day, status, figure, alert["id"]),
        )

    judged = await asha.rows(entry["watchlist_id"])

    assert (unjudged["alert"]["rule"], unjudged["verdict"]) == ("move_beyond", None)
    assert judged["triggered"] == 1
    assert judged["rows"][0]["verdict"] == {
        "trade_date": str(date(2025, 12, 31)),
        "status": "triggered",
        "figure": 0.0003,
        "paused_reason": None,
    }


async def test_a_person_s_rows_are_invisible_to_another(asha: Person, ravi: Person) -> None:
    watchlist = (await asha.follow(HDFC_BANK))["watchlist_id"]
    banks = (await ravi.send("POST", "/watchlists", {"name": "Banks"})).json()["id"]

    refused = await ravi.send("GET", f"/watchlists/{watchlist}/rows")
    empty = await ravi.rows(banks)

    assert (refused.status_code, refused.json()["detail"]) == (
        404,
        {"reason": "watchlist_not_found"},
    )
    assert (empty["rows"], empty["triggered"]) == ([], 0)
