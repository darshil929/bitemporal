"""Who a request acts for, read from its session cookie, with the session's limits enforced."""

import base64
import hashlib
import secrets
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import APIRouter
from psycopg.rows import namedtuple_row

from api.config import ApiSettings
from api.dependencies import AdminDependency
from api.main import create_app
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

COOKIE = "__Host-bitemporal_session"
NO_SESSION = {"reason": None, "ended_at": None, "idle_minutes": None, "max_hours": None}
SESSION_ROW = (
    "select created_at, last_seen_at, ended_at, ended_reason from app_session where token_hash = %s"
)
START_SESSION = (
    "insert into app_session (owner_id, token_hash, created_at, last_seen_at, ended_at, ended_reason)"
    " values (%s, %s, now() - %s, now() - %s, case when %s::text is not null then now() - %s end, %s)"
)


def connect(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(
        dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", row_factory=namedtuple_row
    )


def cookie_of(token: bytes) -> str:
    return base64.urlsafe_b64encode(token).rstrip(b"=").decode()


class Sessions:
    """Accounts and sessions the owner of the tables writes, and the API's answer to each cookie."""

    def __init__(self, dsn: str, settings: ApiSettings) -> None:
        self.dsn, self.settings, self.hashes = dsn, settings, {}
        with connect(dsn) as connection:
            self.accounts = {
                name: connection.execute(
                    "insert into app_user (username, display_name, role, password_hash)"
                    " values (%s, %s, %s, 'unused') returning id",
                    (name, name.title(), role),
                ).fetchone()[0]
                for name, role in (("asha", "member"), ("meera", "admin"))
            }

    def start(
        self,
        name: str,
        started: timedelta = timedelta(0),
        seen: timedelta = timedelta(0),
        ended_reason: str | None = None,
    ) -> str:
        """A session started and last active the given time ago, as its cookie's value."""
        token = secrets.token_bytes(32)
        cookie, hashed = cookie_of(token), hashlib.sha256(token).digest()
        values = (self.accounts[name], hashed, started, seen, ended_reason, seen, ended_reason)
        with connect(self.dsn) as connection:
            connection.execute(START_SESSION, values)
        self.hashes[cookie] = hashed
        return cookie

    def stored(self, cookie: str) -> Any:
        with connect(self.dsn) as connection:
            return connection.execute(SESSION_ROW, (self.hashes[cookie],)).fetchone()

    async def answer(
        self,
        cookie: str | None,
        path: str = "/session",
        name: str = COOKIE,
        settings: ApiSettings | None = None,
    ) -> httpx.Response:
        app = create_app(settings or self.settings)
        guarded = APIRouter()

        @guarded.get("/admins-only")
        def admins_only(user: AdminDependency) -> dict[str, str]:
            return {"username": user.username}

        app.include_router(guarded)
        headers = {"Cookie": f"{name}={cookie}"} if cookie else {}
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://api") as api:
                return await api.get(path, headers=headers)


@pytest.fixture
async def sessions(migrated_settings: ApiSettings, postgres_dsn: str) -> AsyncIterator[Sessions]:
    yield Sessions(postgres_dsn, migrated_settings)


async def test_a_running_session_names_the_person_it_acts_for(sessions: Sessions) -> None:
    response = await sessions.answer(sessions.start("asha"))

    assert response.status_code == 200
    assert response.json() == {
        "id": sessions.accounts["asha"],
        "username": "asha",
        "display_name": "Asha",
        "role": "member",
        "must_change_password": False,
    }


@pytest.mark.parametrize("cookie", [None, "not-a-token", cookie_of(bytes(32))])
async def test_a_request_without_a_session_is_refused(
    sessions: Sessions, cookie: str | None
) -> None:
    response = await sessions.answer(cookie)

    assert (response.status_code, response.json()) == (401, {"detail": NO_SESSION})


@pytest.mark.parametrize(
    ("started", "seen", "reason", "lasted"),
    [
        (timedelta(hours=3), timedelta(minutes=121), "idle", timedelta(minutes=120)),
        (timedelta(hours=12, minutes=5), timedelta(minutes=1), "limit", timedelta(hours=12)),
    ],
)
async def test_a_session_past_a_limit_ends_where_the_limit_fell(
    sessions: Sessions, started: timedelta, seen: timedelta, reason: str, lasted: timedelta
) -> None:
    cookie = sessions.start("asha", started, seen)

    detail = (await sessions.answer(cookie)).json()["detail"]

    row = sessions.stored(cookie)
    assert (detail["reason"], detail["idle_minutes"], detail["max_hours"]) == (reason, 120, 12)
    assert row.ended_reason == reason
    assert row.ended_at - (row.last_seen_at if reason == "idle" else row.created_at) == lasted


async def test_a_disabled_account_s_session_ends(sessions: Sessions) -> None:
    cookie = sessions.start("asha")
    with connect(sessions.dsn) as connection:
        connection.execute("update app_user set disabled_at = now() where username = 'asha'")

    response = await sessions.answer(cookie)

    assert (response.status_code, response.json()["detail"]["reason"]) == (401, "disabled")
    assert sessions.stored(cookie).ended_reason == "disabled"


async def test_an_ended_session_says_why_and_when(sessions: Sessions) -> None:
    cookie = sessions.start("asha", timedelta(hours=2), timedelta(hours=1), "signed_out")

    detail = (await sessions.answer(cookie)).json()["detail"]

    assert detail["reason"] == "signed_out"
    assert detail["ended_at"] is not None


@pytest.mark.parametrize(
    ("seen", "recorded"), [(timedelta(minutes=5), True), (timedelta(seconds=10), False)]
)
async def test_activity_is_recorded_at_most_once_a_minute(
    sessions: Sessions, seen: timedelta, recorded: bool
) -> None:
    cookie = sessions.start("asha", seen, seen)
    before = sessions.stored(cookie).last_seen_at

    await sessions.answer(cookie)

    assert (sessions.stored(cookie).last_seen_at > before) is recorded


@pytest.mark.parametrize(("name", "status"), [("bitemporal_session", 200), (COOKIE, 401)])
async def test_over_plain_http_the_cookie_takes_no_host_prefix(
    sessions: Sessions, name: str, status: int
) -> None:
    plain = sessions.settings.model_copy(update={"session_cookie_secure": False})

    response = await sessions.answer(sessions.start("asha"), name=name, settings=plain)

    assert response.status_code == status


@pytest.mark.parametrize(("person", "status"), [("meera", 200), ("asha", 403)])
async def test_an_admin_route_serves_admins_alone(
    sessions: Sessions, person: str, status: int
) -> None:
    response = await sessions.answer(sessions.start(person), "/admins-only")

    assert response.status_code == status
