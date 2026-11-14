"""How current the market data is: the day the pages show, the last run, and the state they make."""

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb

from api.config import ApiSettings
from api.services import data_status
from api.services.data_status import INDIA
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

# The marts as dbt builds them over the tables the owner writes here.
STAND_INS = (
    (
        "create view mart_trading_days as select venue, trade_date, as_of_date, is_complete, bars,"
        " divergent_instruments, detail from trading_day"
    ),
    (
        "create table mart_source_days (source_id text, trade_date date, outcome text,"
        " fetched_at timestamptz default now())"
    ),
    "create table mart_sources (source_id text, first_day date)",
)
MARTS = ("mart_trading_days", "mart_source_days", "mart_sources")
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
REQUEST = (
    "insert into flow_request (flow, first_day, last_day, requested_by, status, started_at, run_id)"
    " select 'sync', '2026-10-04', '2026-10-10', id, %s, %s, 'live' from app_user"
)
STEP = (
    "insert into flow_run_step (run_id, step, started_at, ended_at, outcome)"
    " values (%s, %s, now(), now() + %s * interval '1 second', 'succeeded')"
)
SOURCE_DAY = "insert into mart_source_days (source_id, trade_date, outcome) values (%s, %s, %s)"
WARNED = {"name": "assert_capital_actions_reported_by_both_venues", "rows": 16}
SHORT_ANSWER = {"source": "bse_corporate_actions", "key": "20260101-20261231", "detail": "short"}


class Status:
    """Runs, releases and answers the tables' owner writes in the migrated schema, and the data
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
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Status]:
    written = Status(postgres_dsn, start_api, migrated_settings, member_headers)
    for statement in STAND_INS:
        written.execute(statement)
    for mart in MARTS:
        written.execute(f"grant select on {mart} to bitemporal_api")
    at(monkeypatch, "2026-10-10 14:00")
    yield written
    for mart in MARTS:
        kind = "view" if mart == "mart_trading_days" else "table"
        written.execute(f"drop {kind} if exists {mart}")


def at(monkeypatch: pytest.MonkeyPatch, moment: str) -> None:
    """India time as `moment`."""
    now = datetime.fromisoformat(moment).replace(tzinfo=INDIA)
    monkeypatch.setattr(data_status, "india_now", lambda: now)


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
        "stale_since": None,
        "days_never_asked": 0,
        "running": None,
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
        {"venue": "BSE", "latest_day": "2026-10-09", "is_complete": True, "bars": 2500},
        {"venue": "NSE", "latest_day": "2026-10-09", "is_complete": True, "bars": 2500},
    ]
    assert shown["last_run"] | {"started_at": None, "ended_at": None} == {
        "flow": "sync",
        "first_day": "2026-10-03",
        "last_day": "2026-10-09",
        "started_at": None,
        "ended_at": None,
        "outcome": "succeeded",
        "checks_passed": 162,
        "failed_steps": [],
        "failed_stages": [],
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
    assert (failed["last_run"]["failed_steps"], failed["last_run"]["failed_stages"]) == (
        ["dbt_models"],
        ["models"],
    )
    assert (failed["last_run"]["failed_fetches"], failed["last_run"]["failed_checks"]) == (1, 1)
    assert (await status.read()).json()["state"] == state


@pytest.mark.parametrize(
    ("moment", "state", "stale_since"),
    [
        ("2026-10-13 09:00", "stale", "2026-10-12"),
        ("2026-10-13 07:00", "fresh", None),
        ("2026-10-12 22:00", "fresh", None),
    ],
)
async def test_a_weekday_ended_without_figures_is_stale_once_its_files_were_due(
    status: Status, monkeypatch: pytest.MonkeyPatch, moment: str, state: str, stale_since: str
) -> None:
    """With the pages on Friday 9 Oct, Monday's files are due by 07:30 on Tuesday."""
    status.published("2026-10-09")
    status.run("2026-10-09 16:01:00+00")
    at(monkeypatch, moment)

    shown = (await status.read()).json()

    assert (shown["state"], shown["stale_since"]) == (state, stale_since)


@pytest.mark.parametrize(
    ("unpublished", "stale_since"),
    [
        (("bse_bhavcopy_equity", "nse_bhavcopy_equity"), None),
        (("bse_bhavcopy_equity",), "2026-10-20"),
    ],
)
async def test_a_weekday_both_venues_published_nothing_for_was_no_session(
    status: Status,
    monkeypatch: pytest.MonkeyPatch,
    unpublished: tuple[str, ...],
    stale_since: str | None,
) -> None:
    status.published("2026-10-19")
    status.run("2026-10-19 16:01:00+00")
    for source in unpublished:
        status.execute(SOURCE_DAY, (source, "2026-10-20", "not_published"))
    at(monkeypatch, "2026-10-21 09:00")

    assert (await status.read()).json()["stale_since"] == stale_since


async def test_days_no_daily_file_was_asked_for_are_counted_to_the_latest_day_a_run_covered(
    status: Status,
) -> None:
    """The bootstrap's second run covers the older years, so it ends before the first."""
    status.execute("insert into mart_sources values ('nse_bhavcopy_equity', '2026-10-01')")
    for day in ("2026-10-01", "2026-10-02", "2026-10-05"):
        status.execute(SOURCE_DAY, ("nse_delivery", day, "succeeded"))
    status.run("2026-10-05 16:01:00+00", first="2026-10-04", last="2026-10-05")
    status.run("2026-10-05 17:01:00+00", first="2026-10-01", last="2026-10-03")

    assert (await status.read()).json()["days_never_asked"] == 2


async def test_the_data_status_is_for_people_signed_in(status: Status) -> None:
    assert (await status.read(signed_in=False)).status_code == 401


async def test_a_waiting_request_makes_the_data_updating(status: Status) -> None:
    status.published("2026-10-09")
    status.run("2026-10-09 16:01:00+00")
    status.execute(REQUEST, ("requested", None))

    shown = (await status.read()).json()

    assert shown["state"] == "updating"
    assert shown["running"] | {"requested_at": None} == {
        "flow": "sync",
        "first_day": "2026-10-04",
        "last_day": "2026-10-10",
        "status": "requested",
        "requested_at": None,
        "started_at": None,
        "current_stage": None,
        "time_left": None,
    }


async def test_a_running_sync_names_its_stage_and_the_time_left(status: Status) -> None:
    """The time left is the steps not yet finished, as the last runs took them."""
    status.published("2026-10-09")
    status.run("2026-10-09 16:01:00+00")
    for step, seconds in (("bse_bhavcopy", 20), ("dbt_models", 700)):
        status.execute(STEP, ("2026-10-09 16:01:00+00", step, seconds))
    status.execute(REQUEST, ("started", "2026-10-10 15:00+00"))
    status.execute(STEP, ("live", "bse_bhavcopy", 18))
    status.execute(
        "create table mart_fetch_attempts (ingestion_id bigint, source_id text, partition_key text,"
        " outcome text, fetched_at timestamptz, detail text)"
    )
    status.execute("grant select on mart_fetch_attempts to bitemporal_api")

    running = (await status.read()).json()["running"]

    status.execute("drop table mart_fetch_attempts")
    assert (running["status"], running["current_stage"]) == ("running", "models")
    assert running["time_left"] == {"seconds": 700, "minutes": 12}


async def test_a_failure_or_staleness_outranks_a_sync_running(
    status: Status, monkeypatch: pytest.MonkeyPatch
) -> None:
    status.published("2026-10-09")
    status.run("2026-10-09 16:01:00+00")
    status.execute(REQUEST, ("requested", None))
    at(monkeypatch, "2026-10-13 09:00")
    stale = (await status.read()).json()["state"]
    status.run("2026-10-12 16:01:00+00", "failed", steps=Jsonb(["dbt_models"]))

    assert (stale, (await status.read()).json()["state"]) == ("stale", "failed")
