"""How current the market data is: the day the pages show, the last run, and the state they make."""

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb

from api.config import ApiSettings
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

# The verdicts as the trading days mart presents them, one per venue and day.
TRADING_DAYS = (
    "create view mart_trading_days as select venue, trade_date, as_of_date, is_complete, bars,"
    " divergent_instruments, detail from trading_day"
)
VERDICT = (
    "insert into trading_day"
    " (venue, trade_date, as_of_date, is_complete, bars, divergent_instruments, detail)"
    " values (%s, %s, %s, true, 2500, 0, null)"
)
RELEASE = (
    "insert into feature_release (table_name, trade_date, row_count)"
    " values ('daily_features_a', %s, 2500)"
)
RUN = (
    "insert into flow_run (run_id, flow, first_day, last_day, started_at, ended_at, outcome,"
    " checks_passed, failures, warned_checks, failed_checks, failed_steps, unmaterialized)"
    " values (%(run)s, 'sync', %(first)s, %(last)s, %(started)s, %(started)s, %(outcome)s, 162,"
    " %(failures)s, %(warned)s, %(failed)s, %(steps)s, %(steps)s)"
)
WARNED = {"name": "assert_capital_actions_reported_by_both_venues", "rows": 16}
SHORT_ANSWER = {"source": "bse_corporate_actions", "key": "20260101-20261231", "detail": "short"}


class Status:
    """Runs and releases the tables' owner writes in the migrated schema, and the data
    status the API shows a member over them."""

    def __init__(
        self, dsn: str, start_api: StartApi, settings: ApiSettings, headers: dict[str, str]
    ) -> None:
        self.dsn, self.start_api, self.settings, self.headers = dsn, start_api, settings, headers

    def execute(self, statement: str, values: tuple[Any, ...] | dict[str, Any] = ()) -> None:
        options = f"-csearch_path={MIGRATION_SCHEMA},public"
        with psycopg.connect(self.dsn, options=options, autocommit=True) as owner:
            owner.execute(statement, values)

    def published(self, day: str) -> None:
        self.execute(RELEASE, (day,))
        for venue in ("BSE", "NSE"):
            self.execute(VERDICT, (venue, day, day))

    def run(self, started: str, outcome: str = "succeeded", **changed: Any) -> None:
        values = {
            "run": started,
            "first": "2026-10-03",
            "last": started[:10],
            "started": started,
            "outcome": outcome,
            "failures": Jsonb([]),
            "warned": Jsonb([WARNED]),
            "failed": Jsonb([]),
            "steps": Jsonb([]),
        }
        self.execute(RUN, values | changed)

    async def read(self, signed_in: bool = True) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.get("/data/status", headers=self.headers if signed_in else {})


@pytest.fixture
def status(
    start_api: StartApi,
    migrated_settings: ApiSettings,
    member_headers: dict[str, str],
    postgres_dsn: str,
) -> Iterator[Status]:
    written = Status(postgres_dsn, start_api, migrated_settings, member_headers)
    written.execute(TRADING_DAYS)
    written.execute("grant select on mart_trading_days to bitemporal_api")
    yield written
    written.execute("drop view if exists mart_trading_days")


async def test_the_seed_dataset_shows_its_last_day_with_no_run_recorded(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> None:
    async with start_api(dataset_settings) as api:
        response = await api.get("/data/status", headers=dataset_member_headers)

    body = response.json()
    assert response.status_code == 200
    assert (body["state"], body["published_day"]) == ("unknown", "2025-12-31")
    assert [venue["latest_day"] for venue in body["venues"]] == ["2025-12-31", "2025-12-31"]


async def test_with_no_run_recorded_the_state_is_unknown(status: Status) -> None:
    assert (await status.read()).json() == {
        "state": "unknown",
        "published_day": None,
        "venues": [],
        "last_run": None,
    }


async def test_a_last_run_with_a_warned_check_alone_is_fresh(
    status: Status,
) -> None:
    status.published("2026-10-09")
    status.run("2026-10-09 16:01:00+00")

    shown = (await status.read()).json()

    assert shown["state"] == "fresh"
    assert shown["published_day"] == "2026-10-09"
    assert shown["venues"] == [
        {"venue": "BSE", "latest_day": "2026-10-09", "is_complete": True},
        {"venue": "NSE", "latest_day": "2026-10-09", "is_complete": True},
    ]
    assert shown["last_run"] | {"started_at": None, "ended_at": None} == {
        "flow": "sync",
        "first_day": "2026-10-03",
        "last_day": "2026-10-09",
        "started_at": None,
        "ended_at": None,
        "outcome": "succeeded",
        "failed_steps": [],
        "failed_fetches": 0,
        "failed_checks": 0,
        "warned_checks": 1,
    }


@pytest.mark.parametrize(
    ("later", "state"),
    [("succeeded", "fresh"), ("cancelled", "failed")],
)
async def test_a_failed_run_stands_until_a_later_run_judges_again(
    status: Status, later: str, state: str
) -> None:
    """A cancelled run ended before it judged anything."""
    status.published("2026-10-09")
    status.run(
        "2026-10-09 16:01:00+00",
        "failed",
        failures=Jsonb([SHORT_ANSWER]),
        failed=Jsonb([WARNED]),
        steps=Jsonb(["dbt_models"]),
    )
    failed = (await status.read()).json()
    status.run("2026-10-10 02:01:00+00", later)

    assert failed["state"] == "failed"
    assert failed["last_run"]["failed_steps"] == ["dbt_models"]
    assert (failed["last_run"]["failed_fetches"], failed["last_run"]["failed_checks"]) == (1, 1)
    assert (await status.read()).json()["state"] == state


async def test_the_data_status_is_for_people_signed_in(status: Status) -> None:
    assert (await status.read(signed_in=False)).status_code == 401
