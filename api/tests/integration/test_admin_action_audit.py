"""Every change an admin makes, recorded once and read by admins alone."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege, RestrictViolation
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.config import ApiSettings
from api.db.database import Database
from api.main import create_app
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

COOKIE = "__Host-bitemporal_session"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
MEERA = {"username": "meera", "display_name": "Meera Iyer", "password": "a long first passphrase"}

ADDED_MEMBER = (
    "insert into audit_event (occurred_at, actor_id, action, subject_id, detail)"
    " values (now() + interval '1 minute', %s, 'person_added', %s, '{\"role\": \"member\"}')"
)


def owner(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", autocommit=True)


def account(dsn: str, username: str) -> int:
    with owner(dsn) as connection:
        found = connection.execute("select id from app_user where username = %s", (username,))
        return int(found.fetchone()[0])  # type: ignore[index]


@pytest.fixture
async def api(migrated_settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


@pytest.fixture
async def admin(api: httpx.AsyncClient) -> dict[str, str]:
    """The first admin's session, from first-run setup."""
    created = await api.post("/setup/admin", json=MEERA, headers=SAME_ORIGIN)
    return {"Cookie": f"{COOKIE}={created.cookies[COOKIE]}"}


async def as_api_role(settings: ApiSettings, user_id: int, statement: str) -> Any:
    database = Database(settings)
    try:
        async with database.transaction(user_id) as transaction:
            return (await transaction.execute(text(statement))).scalar_one_or_none()
    finally:
        await database.close()


async def test_first_run_setup_records_the_first_admin(
    api: httpx.AsyncClient, admin: dict[str, str]
) -> None:
    entries = (await api.get("/admin/audit", headers=admin)).json()

    assert [(e["action"], e["actor_name"], e["subject_name"], e["detail"]) for e in entries] == [
        ("first_admin_created", "Meera Iyer", "Meera Iyer", {})
    ]


async def test_actions_read_newest_first_with_who_acted_and_on_whom(
    api: httpx.AsyncClient, admin: dict[str, str], member_headers: dict[str, str], postgres_dsn: str
) -> None:
    with owner(postgres_dsn) as connection:
        connection.execute(
            ADDED_MEMBER, (account(postgres_dsn, "meera"), account(postgres_dsn, "reader"))
        )

    entries = (await api.get("/admin/audit", headers=admin)).json()

    assert [(e["action"], e["subject_name"], e["detail"]) for e in entries] == [
        ("person_added", "Reader", {"role": "member"}),
        ("first_admin_created", "Meera Iyer", {}),
    ]


async def test_a_member_is_refused_and_reads_no_record(
    api: httpx.AsyncClient,
    admin: dict[str, str],
    member_headers: dict[str, str],
    migrated_settings: ApiSettings,
    postgres_dsn: str,
) -> None:
    response = await api.get("/admin/audit", headers=member_headers)
    member = account(postgres_dsn, "reader")

    seen = await as_api_role(migrated_settings, member, "select count(*) from audit_event")

    assert (response.status_code, seen) == (403, 0)


@pytest.mark.parametrize(
    "statement",
    [
        "update audit_event set detail = '{}'",
        "delete from audit_event",
        (
            "insert into audit_event (actor_id, action) select id, 'role_changed' from app_user"
            " where username = 'reader'"
        ),
    ],
)
async def test_the_api_cannot_change_remove_or_misattribute_a_record(
    admin: dict[str, str],
    member_headers: dict[str, str],
    migrated_settings: ApiSettings,
    postgres_dsn: str,
    statement: str,
) -> None:
    with pytest.raises(DBAPIError) as refused:
        await as_api_role(migrated_settings, account(postgres_dsn, "meera"), statement)

    assert isinstance(refused.value.orig, InsufficientPrivilege)


async def test_no_one_changes_a_recorded_action(admin: dict[str, str], postgres_dsn: str) -> None:
    with owner(postgres_dsn) as connection, pytest.raises(RestrictViolation):
        connection.execute("update audit_event set action = 'role_changed'")


async def test_the_record_is_refused_without_a_session(api: httpx.AsyncClient) -> None:
    assert (await api.get("/admin/audit")).status_code == 401
