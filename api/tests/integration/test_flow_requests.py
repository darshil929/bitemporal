"""Admins ask for a sync or the bootstrap; the request is recorded with an audit event."""

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

SYNC_WEEK = {"first_day": "2026-11-04", "last_day": "2026-11-10"}
AUDIT = "select action, detail from audit_event order by id"


class Requests:
    def __init__(self, dsn: str, start_api: StartApi, settings: ApiSettings) -> None:
        self.dsn, self.start_api, self.settings = dsn, start_api, settings

    def execute(self, statement: str, values: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        options = f"-csearch_path={MIGRATION_SCHEMA},public"
        with psycopg.connect(self.dsn, options=options, autocommit=True) as owner:
            cursor = owner.execute(statement, values)
            return cursor.fetchall() if cursor.description else []

    async def send(
        self, method: str, path: str, headers: dict[str, str], body: Any = None
    ) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.request(
                method, path, json=body, headers=headers | {"Sec-Fetch-Site": "same-origin"}
            )


@pytest.fixture
def requests(
    start_api: StartApi,
    migrated_settings: ApiSettings,
    postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Requests]:
    written = Requests(postgres_dsn, start_api, migrated_settings)
    written.execute("create table mart_sources (source_id text, first_day date)")
    written.execute("grant select on mart_sources to bitemporal_api")
    written.execute("insert into mart_sources values ('nse_bhavcopy_equity', '2011-06-22')")
    now = datetime(2026, 11, 10, 21, 0, tzinfo=INDIA)
    monkeypatch.setattr(data_status, "india_now", lambda: now)
    yield written
    written.execute("drop table if exists mart_sources")


async def test_an_admin_s_sync_request_is_recorded_and_audited(
    requests: Requests, admin_headers: dict[str, str]
) -> None:
    response = await requests.send("POST", "/data/sync", admin_headers, SYNC_WEEK)

    added = response.json()
    assert response.status_code == 202
    assert (added["flow"], added["status"], added["runs"]) == ("sync", "requested", [])
    assert (added["first_day"], added["last_day"]) == ("2026-11-04", "2026-11-10")
    assert requests.execute(AUDIT) == [("sync_started", {"request_id": added["id"], **SYNC_WEEK})]


async def test_a_bootstrap_covers_the_whole_history_to_today(
    requests: Requests, admin_headers: dict[str, str]
) -> None:
    added = (await requests.send("POST", "/data/bootstrap", admin_headers)).json()

    assert (added["flow"], added["first_day"], added["last_day"]) == (
        "bootstrap",
        "2011-06-22",
        "2026-11-10",
    )
    assert requests.execute(AUDIT)[0][0] == "bootstrap_started"


@pytest.mark.parametrize("status", ["requested", "started"])
async def test_no_request_is_taken_while_another_waits_or_runs(
    requests: Requests, admin_headers: dict[str, str], status: str
) -> None:
    first = (await requests.send("POST", "/data/sync", admin_headers, SYNC_WEEK)).json()
    if status == "started":
        requests.execute(
            "update flow_request set status = 'started', started_at = now() where id = %s",
            (first["id"],),
        )

    refused = await requests.send("POST", "/data/bootstrap", admin_headers)

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        {"reason": "request_pending", "request_id": first["id"]},
    )
    assert len(requests.execute(AUDIT)) == 1


async def test_a_range_no_flow_can_run_over_is_refused(
    requests: Requests, admin_headers: dict[str, str]
) -> None:
    body = {"first_day": "2026-11-04", "last_day": "2026-11-11"}

    refused = await requests.send("POST", "/data/sync", admin_headers, body)

    assert (refused.status_code, refused.json()["detail"]) == (422, {"reason": "after_today"})
    assert requests.execute("select count(*) from flow_request") == [(0,)]


async def test_a_request_shows_its_refusal_or_its_runs(
    requests: Requests, admin_headers: dict[str, str]
) -> None:
    refused = (await requests.send("POST", "/data/sync", admin_headers, SYNC_WEEK)).json()
    why = {"reason": "flow_running", "first_day": "2026-11-03", "last_day": "2026-11-09"}
    requests.execute(
        "update flow_request set status = 'refused', refusal = %s where id = %s",
        (Jsonb(why), refused["id"]),
    )
    ran = (await requests.send("POST", "/data/sync", admin_headers, SYNC_WEEK)).json()
    requests.execute(
        "update flow_request set status = 'finished', started_at = now(), finished_at = now()"
        " where id = %s",
        (ran["id"],),
    )
    requests.execute(
        "insert into flow_run (run_id, flow, first_day, last_day, started_at, ended_at, outcome,"
        " checks_passed, request_id) values ('run', 'sync', '2026-11-04', '2026-11-10', now(),"
        " now(), 'succeeded', 0, %s)",
        (ran["id"],),
    )

    shown = [
        (await requests.send("GET", f"/data/requests/{request}", admin_headers)).json()
        for request in (refused["id"], ran["id"])
    ]

    assert (shown[0]["status"], shown[0]["refusal"]) == ("refused", why)
    assert (shown[1]["status"], shown[1]["requested_by"]) == ("finished", "Meera")
    assert shown[1]["runs"] == [
        {
            "run_id": "run",
            "first_day": "2026-11-04",
            "last_day": "2026-11-10",
            "outcome": "succeeded",
        }
    ]


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/data/sync"), ("POST", "/data/bootstrap"), ("GET", "/data/requests/1")],
)
async def test_requests_are_for_admins(
    requests: Requests, member_headers: dict[str, str], method: str, path: str
) -> None:
    response = await requests.send(method, path, member_headers, SYNC_WEEK)

    assert response.status_code == 403
