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
    " finished_at, cancel_requested_at, run_id) select 'sync', '2026-11-04', '2026-11-10', id,"
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

    def request(self, status: str = "started", cancel: bool = False) -> int:
        """A request of the status, with the times its status carries."""
        moment = "2026-11-10 16:00+00"
        values = {
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
    for run_id in ("run-a", "run-b", "run-c"):
        written.run(run_id, SYNC_STEPS)
    yield written


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
