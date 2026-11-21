"""The run history admins read: the newest runs with their reports, and the days never asked for."""

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

# The marts as dbt builds them, written here directly.
STAND_INS = {
    "mart_source_days": "(source_id text, trade_date date, outcome text)",
    "mart_sources": "(source_id text, first_day date)",
}
RUN = (
    "insert into flow_run (run_id, flow, first_day, last_day, started_at, ended_at, outcome,"
    " counts, checks_passed, failures, warned_checks, failed_checks, failed_steps, request_id)"
    " values (%(run)s, 'sync', '2026-10-01', %(last)s, %(started)s, %(started)s, %(outcome)s,"
    " %(counts)s, 162, %(failures)s, %(warned)s, '[]', %(steps)s, %(request)s)"
)
PRICES = {"published": 5, "unpublished": 2, "failed": 0}
SHORT_ANSWER = {"source": "bse_corporate_actions", "key": "20260101-20261231", "detail": "short"}
WARNED = {"name": "assert_capital_actions_reported_by_both_venues", "rows": 16}


class History:
    """Runs and answers the tables' owner writes in the migrated schema, and the history the API
    shows over them."""

    def __init__(self, dsn: str, start_api: StartApi, settings: ApiSettings) -> None:
        self.dsn, self.start_api, self.settings = dsn, start_api, settings

    def execute(self, statement: str, values: tuple[Any, ...] | dict[str, Any] = ()) -> None:
        options = f"-csearch_path={MIGRATION_SCHEMA},public"
        with psycopg.connect(self.dsn, options=options, autocommit=True) as owner:
            owner.execute(statement, values)

    def run(self, day: int, outcome: str = "succeeded", **changed: Any) -> None:
        values = {
            "run": f"run-{day:02}",
            "last": f"2026-10-{day:02}",
            "started": f"2026-10-{day:02} 15:00:00+00",
            "outcome": outcome,
            "counts": Jsonb({"nse_bhavcopy": PRICES}),
            "failures": Jsonb([]),
            "warned": Jsonb([]),
            "steps": Jsonb([]),
            "request": None,
        }
        self.execute(RUN, values | changed)

    async def read(self, headers: dict[str, str]) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.get("/data/runs", headers=headers)


@pytest.fixture
def history(
    start_api: StartApi, migrated_settings: ApiSettings, postgres_dsn: str
) -> Iterator[History]:
    written = History(postgres_dsn, start_api, migrated_settings)
    for mart, columns in STAND_INS.items():
        written.execute(f"create table {mart} {columns}")
        written.execute(f"grant select on {mart} to bitemporal_api")
    yield written
    for mart in STAND_INS:
        written.execute(f"drop table if exists {mart}")


async def test_an_admin_reads_the_ten_newest_runs_with_their_reports(
    history: History, admin_headers: dict[str, str]
) -> None:
    for day in range(1, 11):
        history.run(day)
    history.run(
        11,
        "failed",
        failures=Jsonb([SHORT_ANSWER]),
        warned=Jsonb([WARNED]),
        steps=Jsonb(["dbt_models"]),
    )
    history.run(12, "cancelled")

    runs = (await history.read(admin_headers)).json()["runs"]

    assert [run["run_id"] for run in runs] == [f"run-{day:02}" for day in range(12, 2, -1)]
    assert {key: runs[1][key] for key in ("outcome", "counts", "failures", "warned_checks")} == {
        "outcome": "failed",
        "counts": {"nse_bhavcopy": PRICES},
        "failures": [SHORT_ANSWER],
        "warned_checks": [WARNED],
    }
    assert (runs[1]["failed_steps"], runs[1]["failed_stages"]) == (["dbt_models"], ["models"])


async def test_days_never_asked_for_are_given_as_stretches(
    history: History, admin_headers: dict[str, str]
) -> None:
    history.execute("insert into mart_sources values ('bse_bhavcopy_equity', '2026-10-01')")
    for day in ("2026-10-01", "2026-10-05"):
        history.execute(
            "insert into mart_source_days values ('bse_delivery', %s, 'succeeded')", (day,)
        )
    history.run(7)

    assert (await history.read(admin_headers)).json()["days_never_asked"] == [
        {"first_day": "2026-10-02", "last_day": "2026-10-04"},
        {"first_day": "2026-10-06", "last_day": "2026-10-07"},
    ]


async def test_with_no_run_recorded_the_history_is_empty(
    history: History, admin_headers: dict[str, str]
) -> None:
    assert (await history.read(admin_headers)).json() == {
        "runs": [],
        "days_never_asked": [],
        "published_instruments": 0,
    }


async def test_the_run_history_is_for_admins(
    history: History, member_headers: dict[str, str]
) -> None:
    assert (await history.read(member_headers)).status_code == 403


async def test_a_run_names_the_admin_who_asked_for_it(
    history: History, admin_headers: dict[str, str]
) -> None:
    """A run started from the command line or the schedule names no one."""
    history.execute(
        "insert into flow_request (flow, first_day, last_day, requested_by, status, started_at,"
        " finished_at) select 'sync', '2026-10-01', '2026-10-02', id, 'finished', now(), now()"
        " from app_user where role = 'admin'"
    )
    history.run(2)
    history.run(3, request=1)

    runs = (await history.read(admin_headers)).json()["runs"]

    assert [(run["run_id"], run["requested_by"], run["duration_seconds"]) for run in runs] == [
        ("run-03", "Meera", 0),
        ("run-02", None, 0),
    ]


async def test_the_history_counts_the_instruments_the_pages_show(
    start_api: StartApi,
    dataset_settings: ApiSettings,
    seeded_models: psycopg.Connection,
    dataset_admin_headers: dict[str, str],
) -> None:
    held = seeded_models.execute(
        "select count(*) from mart_daily_features where trade_date = '2025-12-31'"
    ).fetchone()

    async with start_api(dataset_settings) as api:
        shown = (await api.get("/data/runs", headers=dataset_admin_headers)).json()

    assert held is not None and held[0] > 0
    assert shown["published_instruments"] == held[0]
