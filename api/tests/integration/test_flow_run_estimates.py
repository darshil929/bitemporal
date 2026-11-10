"""How long a sync or the bootstrap would take: days to ask for, and the last runs' fixed work."""

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from api.services import data_status
from api.services.data_status import INDIA
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

STAND_INS = {
    "mart_source_days": "(source_id text, trade_date date, outcome text)",
    "mart_sources": "(source_id text, first_day date)",
}
FIRST_DAYS = {
    "bse_bhavcopy_equity": "2016-12-12",
    "nse_bhavcopy_equity": "2011-06-22",
    "bse_delivery": "2010-01-01",
    "nse_delivery": "2011-06-22",
}
RUN = (
    "insert into flow_run (run_id, flow, first_day, last_day, started_at, ended_at, outcome,"
    " checks_passed) values (%s, %s, '2026-11-01', '2026-11-07', %s,"
    " %s::timestamptz + %s * interval '1 second', %s, 0)"
)
STEP = (
    "insert into flow_run_step (run_id, step, started_at, ended_at, outcome)"
    " values (%s, %s, %s, %s::timestamptz + %s * interval '1 second', 'succeeded')"
)
SYNC_WEEK = {"first_day": "2026-11-04", "last_day": "2026-11-10"}


class Estimates:
    def __init__(self, dsn: str, start_api: StartApi, settings: ApiSettings) -> None:
        self.dsn, self.start_api, self.settings = dsn, start_api, settings

    def execute(self, statement: str, values: tuple[Any, ...] = ()) -> None:
        options = f"-csearch_path={MIGRATION_SCHEMA},public"
        with psycopg.connect(self.dsn, options=options, autocommit=True) as owner:
            owner.execute(statement, values)

    def run(self, run_id: str, started: str, steps: dict[str, int], **changed: Any) -> None:
        """A run of the flow whose steps took the given seconds, one after another."""
        flow, outcome = changed.get("flow", "sync"), changed.get("outcome", "succeeded")
        self.execute(RUN, (run_id, flow, started, started, sum(steps.values()), outcome))
        for step, seconds in steps.items():
            self.execute(STEP, (run_id, step, started, started, seconds))

    async def get(self, path: str, headers: dict[str, str], **query: str) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.get(path, headers=headers, params=query)


@pytest.fixture
def estimates(
    start_api: StartApi,
    migrated_settings: ApiSettings,
    postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Estimates]:
    written = Estimates(postgres_dsn, start_api, migrated_settings)
    for mart, columns in STAND_INS.items():
        written.execute(f"create table {mart} {columns}")
        written.execute(f"grant select on {mart} to bitemporal_api")
    for source, first_day in FIRST_DAYS.items():
        written.execute("insert into mart_sources values (%s, %s)", (source, first_day))
    now = datetime(2026, 11, 10, 21, 0, tzinfo=INDIA)
    monkeypatch.setattr(data_status, "india_now", lambda: now)
    yield written
    for mart in STAND_INS:
        written.execute(f"drop table if exists {mart}")


async def test_a_sync_asks_for_each_day_not_held_and_again_for_the_two_latest_held(
    estimates: Estimates, admin_headers: dict[str, str]
) -> None:
    for day in ("2026-11-04", "2026-11-05", "2026-11-06", "2026-11-08", "2026-11-09"):
        estimates.execute(
            "insert into mart_source_days values ('nse_bhavcopy_equity', %s, 'succeeded')", (day,)
        )

    requests = (await estimates.get("/data/sync/estimate", admin_headers, **SYNC_WEEK)).json()[
        "requests"
    ]

    held = {source["source_id"]: source for source in requests["sources"]}
    assert held["nse_bhavcopy_equity"] | {"source_id": None} == {
        "source_id": None,
        "days": 7,
        "held": 5,
        "to_request": 4,
    }
    assert held["bse_delivery"]["to_request"] == 7
    assert requests["duration"] == {"seconds": 14, "minutes": 1}


async def test_the_fixed_work_is_the_median_of_the_last_three_runs_by_stage(
    estimates: Estimates, admin_headers: dict[str, str]
) -> None:
    """Fetching is the requests' part; a cancelled run and older runs are not measured."""
    for day, models in (("2026-11-06", 690), ("2026-11-07", 750), ("2026-11-09", 970)):
        steps = {
            "nse_bhavcopy": 20,
            "dbt_models": models,
            "daily_features": 180,
            "instrument_identity": 90,
        }
        estimates.run(f"run-{day}", f"{day} 15:00+00", steps)
    estimates.run("older", "2026-10-31 15:00+00", {"dbt_models": 3000})
    estimates.run("cancelled", "2026-11-10 15:00+00", {"dbt_models": 10}, outcome="cancelled")

    fixed = (await estimates.get("/data/sync/estimate", admin_headers, **SYNC_WEEK)).json()["fixed"]

    assert fixed["stages"] == {
        "features": {"seconds": 180, "minutes": 3},
        "models": {"seconds": 750, "minutes": 13},
        "other": {"seconds": 90, "minutes": 2},
    }
    assert fixed["duration"] == {"seconds": 1020, "minutes": 17}
    assert sorted(run["seconds"] for run in fixed["last_runs"]) == [980, 1040, 1260]


@pytest.mark.parametrize(
    ("first_day", "last_day", "reason"),
    [
        ("2026-11-10", "2026-11-04", "range_reversed"),
        ("2011-06-21", "2026-11-04", "before_history"),
        ("2026-11-04", "2026-11-11", "after_today"),
    ],
)
async def test_a_range_no_flow_can_run_over_is_refused(
    estimates: Estimates, admin_headers: dict[str, str], first_day: str, last_day: str, reason: str
) -> None:
    response = await estimates.get(
        "/data/sync/estimate", admin_headers, first_day=first_day, last_day=last_day
    )

    assert (response.status_code, response.json()["detail"]) == (422, {"reason": reason})


async def test_a_bootstrap_takes_the_two_latest_years_then_the_rest_unmeasured(
    estimates: Estimates, admin_headers: dict[str, str]
) -> None:
    body = (await estimates.get("/data/bootstrap/estimate", admin_headers)).json()

    windows = [(window["first_day"], window["last_day"]) for window in body["windows"]]
    recent = {source["source_id"]: source["to_request"] for source in body["windows"][0]["sources"]}
    assert windows == [("2024-11-11", "2026-11-10"), ("2011-06-22", "2024-11-10")]
    older = {source["source_id"]: source["days"] for source in body["windows"][1]["sources"]}
    assert recent["nse_bhavcopy_equity"] == 730
    assert older["bse_delivery"] == older["bse_bhavcopy_equity"] == 2891
    assert body["windows"][0]["duration"] == {"seconds": 1460, "minutes": 25}
    assert body["fixed"] is None


@pytest.mark.parametrize("path", ["/data/sync/estimate", "/data/bootstrap/estimate"])
async def test_estimates_are_for_admins(
    estimates: Estimates, member_headers: dict[str, str], path: str
) -> None:
    assert (await estimates.get(path, member_headers, **SYNC_WEEK)).status_code == 403
