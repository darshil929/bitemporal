"""A temporary password an admin sets: replaced at the first sign-in, and refused past its day."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import APIRouter
from psycopg.rows import namedtuple_row

from api.config import ApiSettings
from api.dependencies import SignedInDependency
from api.main import create_app
from api.services.passwords import hash_password, password_problem
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

COOKIE = "__Host-bitemporal_session"
TEMPORARY = "temporary passphrase from an admin"
CHOSEN = "a passphrase only its holder knows"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


def owner(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(
        dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", row_factory=namedtuple_row
    )


@pytest.fixture
def ravi(migrated_settings: ApiSettings, postgres_dsn: str) -> None:
    with owner(postgres_dsn) as connection:
        connection.execute(
            "insert into app_user (username, display_name, role, password_hash,"
            " must_change_password, temporary_password_expires_at)"
            " values ('ravi', 'Ravi Kumar', 'member', %s, true, now() + interval '24 hours')",
            (hash_password(TEMPORARY),),
        )


def stored(dsn: str) -> Any:
    with owner(dsn) as connection:
        return connection.execute("select * from app_user where username = 'ravi'").fetchone()


@pytest.fixture
async def api(migrated_settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_settings)
    guarded = APIRouter()

    @guarded.get("/signed-in-only")
    def signed_in_only(user: SignedInDependency) -> dict[str, str]:
        return {"username": user.username}

    app.include_router(guarded)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


async def signed_in(api: httpx.AsyncClient, password: str = TEMPORARY) -> httpx.Response:
    body = {"username": "ravi", "password": password}
    return await api.post("/auth/sign-in", json=body, headers=SAME_ORIGIN)


def holding(response: httpx.Response) -> dict[str, str]:
    return {"Cookie": f"{COOKIE}={response.cookies[COOKIE]}"} | SAME_ORIGIN


async def test_a_temporary_password_opens_only_the_session_and_its_replacement(
    api: httpx.AsyncClient, ravi: None
) -> None:
    headers = holding(await signed_in(api))

    session = await api.get("/session", headers=headers)
    elsewhere = await api.get("/signed-in-only", headers=headers)

    assert session.json()["must_change_password"] is True
    assert (elsewhere.status_code, elsewhere.json()) == (
        403,
        {"detail": {"reason": "password_change_required"}},
    )


async def test_a_chosen_password_replaces_the_temporary_one(
    api: httpx.AsyncClient, ravi: None, postgres_dsn: str
) -> None:
    headers = holding(await signed_in(api))

    changed = await api.post("/auth/password", json={"password": CHOSEN}, headers=headers)

    account = stored(postgres_dsn)
    assert changed.status_code == 204
    assert (account.must_change_password, account.temporary_password_expires_at) == (False, None)
    assert (await api.get("/signed-in-only", headers=headers)).status_code == 200
    assert (await signed_in(api, CHOSEN)).json()["must_change_password"] is False
    assert (await signed_in(api)).status_code == 401


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("fourteen chars", "too_short"),
        ("x" * 129, "too_long"),
        ("ravi chose this passphrase", "contains_a_name"),
        ("the passphrase of RAVI KUMAR", "contains_a_name"),
        ("my Bitemporal passphrase", "contains_a_name"),
    ],
)
async def test_a_password_the_rule_refuses_leaves_the_temporary_one(
    api: httpx.AsyncClient, ravi: None, postgres_dsn: str, password: str, reason: str
) -> None:
    headers = holding(await signed_in(api))

    refused = await api.post("/auth/password", json={"password": password}, headers=headers)

    assert (refused.status_code, refused.json()) == (422, {"detail": reason})
    assert stored(postgres_dsn).must_change_password is True


async def test_a_change_no_temporary_password_calls_for_is_refused(
    api: httpx.AsyncClient, ravi: None, postgres_dsn: str
) -> None:
    with owner(postgres_dsn) as connection:
        connection.execute("update app_user set must_change_password = false")
    headers = holding(await signed_in(api))

    refused = await api.post("/auth/password", json={"password": CHOSEN}, headers=headers)

    assert (refused.status_code, refused.json()) == (409, {"detail": "no_change_due"})


async def test_a_temporary_password_past_its_day_is_named_only_once_right(
    api: httpx.AsyncClient, ravi: None, postgres_dsn: str
) -> None:
    with owner(postgres_dsn) as connection:
        connection.execute(
            "update app_user set temporary_password_expires_at = now() - interval '1 minute'"
        )

    right, wrong = await signed_in(api), await signed_in(api, "not the password at all")

    assert right.json()["detail"]["reason"] == "temporary_password_expired"
    assert wrong.json()["detail"]["reason"] == "wrong_credentials"


def test_the_rule_is_length_alone_beside_the_names() -> None:
    assert password_problem("fifteen symbols", "ravi") is None
    assert password_problem("!!!!!!!!!!!!!!!") is None
    assert password_problem("a" * 128) is None
