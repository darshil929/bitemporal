"""Signing in and out with a password, and the pause after wrong ones."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import namedtuple_row
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from api.config import ApiSettings
from api.main import create_app
from api.services.passwords import hash_password
from api.services.sign_in import pause_after
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

COOKIE = "__Host-bitemporal_session"
PASSWORD = "a long passphrase of five words"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
WRONG = {"detail": {"reason": "wrong_credentials", "paused_until": None}}


def owner(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(
        dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", row_factory=namedtuple_row
    )


@pytest.fixture
def asha(migrated_settings: ApiSettings, postgres_dsn: str) -> int:
    with owner(postgres_dsn) as connection:
        return int(
            connection.execute(
                "insert into app_user (username, display_name, role, password_hash)"
                " values ('asha', 'Asha', 'member', %s) returning id",
                (hash_password(PASSWORD),),
            ).fetchone()[0]
        )


def account(dsn: str, sql: str = "select * from app_user where username = 'asha'") -> Any:
    with owner(dsn) as connection:
        return connection.execute(sql).fetchone()


@pytest.fixture
async def api(migrated_settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


async def sign_in(api: httpx.AsyncClient, password: str = PASSWORD, username: str = "asha") -> Any:
    body = {"username": username, "password": password}
    return await api.post("/auth/sign-in", json=body, headers=SAME_ORIGIN)


async def test_the_right_password_starts_a_session_the_cookie_carries(
    api: httpx.AsyncClient, asha: int, postgres_dsn: str
) -> None:
    with owner(postgres_dsn) as connection:
        connection.execute("update app_user set failed_sign_ins = 3")

    signed_in = await sign_in(api)

    cookie = signed_in.headers["set-cookie"]
    session = await api.get("/session", headers={"Cookie": f"{COOKIE}={signed_in.cookies[COOKIE]}"})
    assert signed_in.status_code == 200
    assert signed_in.json()["username"] == "asha"
    assert all(
        part in cookie for part in ("HttpOnly", "Max-Age=43200", "Path=/", "SameSite=lax", "Secure")
    )
    assert session.json()["id"] == asha
    assert account(postgres_dsn).failed_sign_ins == 0


async def test_a_wrong_username_and_a_wrong_password_are_refused_alike(
    api: httpx.AsyncClient, asha: int, postgres_dsn: str
) -> None:
    unknown, wrong = await sign_in(api, username="nobody"), await sign_in(api, "not it")

    assert (
        (unknown.status_code, unknown.json()) == (wrong.status_code, wrong.json()) == (401, WRONG)
    )
    assert account(postgres_dsn).failed_sign_ins == 1


async def test_a_fifth_wrong_password_pauses_sign_in_and_the_pause_counts_nothing(
    api: httpx.AsyncClient, asha: int, postgres_dsn: str
) -> None:
    answers = [await sign_in(api, "not it") for _ in range(5)]
    during = await sign_in(api)

    stored = account(postgres_dsn, "select *, now() as now from app_user where username = 'asha'")
    paused = answers[-1].json()["detail"]
    assert [answer.json() for answer in answers[:4]] == [WRONG] * 4
    assert paused["reason"] == "paused"
    assert stored.sign_in_paused_until - stored.now <= timedelta(minutes=1)
    assert during.json()["detail"]["reason"] == "paused"
    assert stored.failed_sign_ins == 5


async def test_a_disabled_account_is_named_only_once_its_password_is_right(
    api: httpx.AsyncClient, asha: int, postgres_dsn: str
) -> None:
    with owner(postgres_dsn) as connection:
        connection.execute("update app_user set disabled_at = now()")

    wrong, right = await sign_in(api, "not it"), await sign_in(api)

    assert wrong.json() == WRONG
    assert right.json()["detail"]["reason"] == "disabled"


async def test_a_hash_with_weaker_settings_is_hashed_again(
    api: httpx.AsyncClient, asha: int, postgres_dsn: str
) -> None:
    weaker = PasswordHash((Argon2Hasher(memory_cost=19456, time_cost=2, parallelism=1),))
    with owner(postgres_dsn) as connection:
        connection.execute("update app_user set password_hash = %s", (weaker.hash(PASSWORD),))

    await sign_in(api)

    assert account(postgres_dsn).password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


async def test_signing_out_ends_the_session_and_drops_the_cookie(
    api: httpx.AsyncClient, asha: int
) -> None:
    headers = {"Cookie": f"{COOKIE}={(await sign_in(api)).cookies[COOKIE]}"}

    signed_out = await api.post("/auth/sign-out", headers=headers | SAME_ORIGIN)
    after = await api.get("/session", headers=headers)

    assert signed_out.status_code == 204
    assert "Max-Age=0" in signed_out.headers["set-cookie"]
    assert after.json()["detail"]["reason"] == "signed_out"


@pytest.mark.parametrize(
    ("failures", "minutes"), [(4, None), (5, 1), (6, 2), (10, 32), (11, 60), (40, 60)]
)
def test_each_wrong_password_after_the_fourth_doubles_the_pause_up_to_an_hour(
    failures: int, minutes: int | None
) -> None:
    assert pause_after(failures) == (timedelta(minutes=minutes) if minutes else None)
