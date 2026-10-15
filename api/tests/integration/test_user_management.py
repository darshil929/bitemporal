"""The people an admin manages, each added with a temporary password shown once."""

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from api.main import create_app
from api.services.temporary_passwords import temporary_password
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
RAVI = {"username": "Ravi", "display_name": "Ravi Kumar", "role": "member"}
TEMPORARY = re.compile(r"^[A-Za-z0-9]{16}$")
EXPIRY = (
    "select temporary_password_expires_at - now() between interval '23 hours 59 minutes'"
    " and interval '24 hours' from app_user where username = 'ravi'"
)


def owner(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", autocommit=True)


@pytest.fixture
async def api(migrated_settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


async def add(api: httpx.AsyncClient, headers: dict[str, str], **person: str) -> httpx.Response:
    return await api.post("/admin/users", json=RAVI | person, headers=headers | SAME_ORIGIN)


async def test_a_person_is_added_with_a_temporary_password_that_opens_the_account_once(
    api: httpx.AsyncClient, admin_headers: dict[str, str], postgres_dsn: str
) -> None:
    added = await add(api, admin_headers)

    body = added.json()
    signed_in = await api.post(
        "/auth/sign-in",
        json={"username": "ravi", "password": body["temporary_password"]},
        headers=SAME_ORIGIN,
    )
    audit = (await api.get("/admin/audit", headers=admin_headers)).json()
    with owner(postgres_dsn) as connection:
        expires_in_a_day = connection.execute(EXPIRY).fetchone()
    assert added.status_code == 201
    assert (body["person"]["username"], body["person"]["must_change_password"]) == ("ravi", True)
    assert TEMPORARY.match(body["temporary_password"])
    assert (signed_in.status_code, signed_in.json()["must_change_password"]) == (200, True)
    assert expires_in_a_day == (True,)
    assert [(e["action"], e["subject_name"], e["detail"]) for e in audit] == [
        ("person_added", "Ravi Kumar", {"role": "member"})
    ]


async def test_people_are_listed_newest_first_with_their_last_sign_in(
    api: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    await add(api, admin_headers)

    listed = (await api.get("/admin/users", headers=admin_headers)).json()

    assert [(p["username"], p["role"], p["last_signed_in"] is None) for p in listed] == [
        ("ravi", "member", True),
        ("meera", "admin", False),
    ]


async def test_a_username_taken_in_any_case_is_refused(
    api: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    await add(api, admin_headers)

    again = await add(api, admin_headers, username="RAVI", display_name="Ravi Shankar")

    assert (again.status_code, again.json()) == (409, {"detail": "username_taken"})


async def test_a_member_manages_no_one(
    api: httpx.AsyncClient, member_headers: dict[str, str]
) -> None:
    refused = [
        await api.get("/admin/users", headers=member_headers),
        await add(api, member_headers),
    ]

    assert [response.status_code for response in refused] == [403, 403]


async def test_people_are_refused_without_a_session(api: httpx.AsyncClient) -> None:
    assert (await api.get("/admin/users")).status_code == 401


def test_a_temporary_password_is_random_letters_and_digits_the_rule_admits() -> None:
    passwords = [temporary_password("xyz", "Xyz Abc") for _ in range(200)]

    assert all(TEMPORARY.match(password) for password in passwords)
    assert not any("xyz" in password.casefold() for password in passwords)
    assert len(set(passwords)) == len(passwords)
