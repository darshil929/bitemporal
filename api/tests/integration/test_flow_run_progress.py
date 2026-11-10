"""A requested run as it goes: its status, its stages in order, and the time left."""

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

REQUEST = (
    "insert into flow_request (flow, first_day, last_day, requested_by, status, started_at,"
    " finished_at, cancel_requested_at, run_id) select %(flow)s, %(first)s, '2026-11-10', id,"
    " %(status)s, %(started)s, %(finished)s, %(cancel)s, 'running' from app_user"
    " where role = 'admin' returning id"
)
RUN = (
    "insert into flow_run (run_id, flow, first_day, last_day, started_at, ended_at, outcome,"
    " checks_passed, request_id) values (%s, 'sync', '2026-11-03', '2026-11-09', %s, %s, %s, 0, %s)"
)
STEP = (
    "insert into flow_run_step (run_id, step, started_at, ended_at, outcome)"
    " values (%s, %s, now(), now() + %s * interval '1 second', %s)"
)
ATTEMPTS_MART = (
    "create table mart_fetch_attempts (ingestion_id bigint generated always as identity,"
    " source_id text, partition_key text, outcome text, fetched_at timestamptz, detail text)"
)
ATTEMPT = (
    "insert into mart_fetch_attempts (source_id, partition_key, outcome, fetched_at, detail)"
    " values (%s, %s, %s, %s, %s)"
)
# A sync's steps and the seconds each took.
SYNC_STEPS = {
    "bse_bhavcopy": 20,
    "instrument_identity": 90,
    "dbt_models": 700,
    "daily_features": 180,
}


class Progress:
    def __init__(self, dsn: str, start_api: StartApi, settings: ApiSettings) -> None:
        self.dsn, self.start_api, self.settings = dsn, start_api, settings

    def execute(self, statement: str, values: tuple[Any, ...] | dict[str, Any] = ()) -> Any:
        options = f"-csearch_path={MIGRATION_SCHEMA},public"
        with psycopg.connect(self.dsn, options=options, autocommit=True) as owner:
            cursor = owner.execute(statement, values)
            return cursor.fetchone() if cursor.description else None

    def run(
        self,
        run_id: str,
        steps: dict[str, int],
        outcome: str = "succeeded",
        request: int | None = None,
    ) -> None:
        self.execute(RUN, (run_id, "2026-11-09 15:00+00", "2026-11-09 15:20+00", outcome, request))
        for step, seconds in steps.items():
            self.execute(STEP, (run_id, step, seconds, "succeeded"))

    def request(self, status: str = "started", cancel: bool = False, flow: str = "sync") -> int:
        """A request of the status, with the times its status carries."""
        moment = "2026-11-10 16:00+00"
        values = {
            "flow": flow,
            "first": "2026-11-04" if flow == "sync" else "2011-06-22",
            "status": status,
            "started": moment if status in ("started", "finished") else None,
            "finished": moment if status == "finished" else None,
            "cancel": moment if cancel else None,
        }
        return int(self.execute(REQUEST, values)[0])

    async def read(self, request: int, headers: dict[str, str]) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.get(f"/data/requests/{request}/progress", headers=headers)


@pytest.fixture
def progress(
    start_api: StartApi,
    migrated_settings: ApiSettings,
    postgres_dsn: str,
    admin_headers: dict[str, str],
) -> Iterator[Progress]:
    written = Progress(postgres_dsn, start_api, migrated_settings)
    written.execute(ATTEMPTS_MART)
    written.execute("grant select on mart_fetch_attempts to bitemporal_api")
    for run_id in ("run-a", "run-b", "run-c"):
        written.run(run_id, SYNC_STEPS)
    yield written
    written.execute("drop table if exists mart_fetch_attempts")


async def test_a_running_sync_shows_its_stages_and_the_steps_left(
    progress: Progress, admin_headers: dict[str, str]
) -> None:
    request = progress.request()
    for step in ("bse_bhavcopy", "instrument_identity"):
        progress.execute(STEP, ("running", step, 1, "succeeded"))

    shown = (await progress.read(request, admin_headers)).json()

    assert shown["status"] == "running"
    assert [(stage["stage"], stage["state"]) for stage in shown["stages"]] == [
        ("prices", "done"),
        ("identity", "done"),
        ("models", "running"),
        ("features", "pending"),
    ]
    assert shown["current_stage"] == "models"
    assert shown["time_left"] == {"seconds": 880, "minutes": 15}


async def test_a_failed_step_fails_its_stage_and_the_run(
    progress: Progress, admin_headers: dict[str, str]
) -> None:
    request = progress.request("finished")
    progress.run("ran", {"bse_bhavcopy": 20}, "failed", request)
    progress.execute(STEP, ("ran", "dbt_models", 5, "failed"))

    shown = (await progress.read(request, admin_headers)).json()

    assert (shown["status"], shown["current_stage"], shown["time_left"]) == ("failed", None, None)
    assert {stage["stage"]: stage["state"] for stage in shown["stages"]}["models"] == "failed"


@pytest.mark.parametrize(
    ("status", "cancel", "outcome", "shown"),
    [
        ("requested", False, None, "requested"),
        ("started", True, None, "cancelling"),
        ("finished", False, "cancelled", "cancelled"),
        ("finished", False, "succeeded", "succeeded"),
        ("cancelled", True, None, "cancelled"),
    ],
)
async def test_a_request_s_status_reads_from_its_record_and_its_runs(
    progress: Progress,
    admin_headers: dict[str, str],
    status: str,
    cancel: bool,
    outcome: str | None,
    shown: str,
) -> None:
    request = progress.request(status, cancel)
    if outcome:
        progress.run("ran", {}, outcome, request)

    assert (await progress.read(request, admin_headers)).json()["status"] == shown


async def test_progress_is_for_admins_and_of_a_request_held(
    progress: Progress, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    request = progress.request()

    assert (await progress.read(request, member_headers)).status_code == 403
    assert (await progress.read(request + 1, admin_headers)).status_code == 404


async def test_a_sync_shows_each_file_s_answer_by_day_and_its_failures(
    progress: Progress, admin_headers: dict[str, str]
) -> None:
    """Attempts before the run started belong to an earlier run; a fetch asked again and read is
    no longer a failure."""
    request = progress.request()
    for attempt in (
        ("nse_bhavcopy_equity", "2026-11-05", "failed", "2026-11-10 15:00+00", "earlier run"),
        ("nse_bhavcopy_equity", "2026-11-04", "succeeded", "2026-11-10 16:01+00", None),
        ("bse_bhavcopy_equity", "2026-11-04", "failed", "2026-11-10 16:01+00", "timed out"),
        ("bse_bhavcopy_equity", "2026-11-04", "succeeded", "2026-11-10 16:02+00", None),
        ("bse_corporate_actions", "20260101-20261231", "failed", "2026-11-10 16:03+00", "403"),
    ):
        progress.execute(ATTEMPT, attempt)

    fetches = (await progress.read(request, admin_headers)).json()["fetches"]

    assert (fetches["first_day"], fetches["last_day"], fetches["years"]) == (
        "2026-11-04",
        "2026-11-10",
        None,
    )
    assert fetches["days"][0] == {
        "day": "2026-11-04",
        "outcomes": {"bse_bhavcopy_equity": "succeeded", "nse_bhavcopy_equity": "succeeded"},
    }
    assert fetches["days"][1] == {"day": "2026-11-05", "outcomes": {}}
    assert fetches["failures"] == [
        {"source": "bse_corporate_actions", "key": "20260101-20261231", "detail": "403"}
    ]


async def test_a_bootstrap_s_older_years_read_by_year_once_its_recent_years_ran(
    progress: Progress, admin_headers: dict[str, str]
) -> None:
    request = progress.request(flow="bootstrap")
    progress.run("recent", {}, "succeeded", request)
    progress.execute(
        ATTEMPT, ("nse_delivery", "2012-03-01", "succeeded", "2026-11-10 17:00+00", None)
    )

    fetches = (await progress.read(request, admin_headers)).json()["fetches"]

    assert (fetches["first_day"], fetches["last_day"], fetches["days"]) == (
        "2011-06-22",
        "2024-11-10",
        None,
    )
    assert fetches["years"][1] == {"year": 2012, "days": 366, "answered": {"nse_delivery": 1}}
