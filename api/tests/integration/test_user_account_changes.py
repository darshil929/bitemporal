"""An admin's changes to an account's role, state and password, each recorded."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from api.main import create_app
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


def account(dsn: str, username: str) -> int:
    options = f"-csearch_path={MIGRATION_SCHEMA},public"
    with psycopg.connect(dsn, options=options) as owner:
        found = owner.execute("select id from app_user where username = %s", (username,))
        return int(found.fetchone()[0])  # type: ignore[index]


@pytest.fixture
async def api(migrated_settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


async def change(
    api: httpx.AsyncClient, headers: dict[str, str], person: int, **body: Any
) -> httpx.Response:
    return await api.patch(f"/admin/users/{person}", json=body, headers=headers | SAME_ORIGIN)


async def recorded(api: httpx.AsyncClient, headers: dict[str, str]) -> list[tuple[Any, ...]]:
    entries = (await api.get("/admin/audit", headers=headers)).json()
    return [(entry["action"], entry["subject_name"], entry["detail"]) for entry in entries]


async def test_a_role_change_is_recorded_with_what_it_was(
    api: httpx.AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    postgres_dsn: str,
) -> None:
    changed = await change(api, admin_headers, account(postgres_dsn, "reader"), role="admin")

    assert (changed.status_code, changed.json()["role"]) == (200, "admin")
    assert await recorded(api, admin_headers) == [
        ("role_changed", "Reader", {"from": "member", "to": "admin"})
    ]


async def test_disabling_an_account_ends_its_sessions_at_once(
    api: httpx.AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    postgres_dsn: str,
) -> None:
    reader = account(postgres_dsn, "reader")

    disabled = await change(api, admin_headers, reader, disabled=True)
    session = await api.get("/session", headers=member_headers)
    enabled = await change(api, admin_headers, reader, disabled=False)

    assert disabled.json()["disabled_at"] is not None
    assert (session.status_code, session.json()["detail"]["reason"]) == (401, "disabled")
    assert enabled.json()["disabled_at"] is None
    assert await recorded(api, admin_headers) == [
        ("account_enabled", "Reader", {}),
        ("account_disabled", "Reader", {}),
    ]


async def test_an_admin_keeps_their_own_account_enabled(
    api: httpx.AsyncClient, admin_headers: dict[str, str], postgres_dsn: str
) -> None:
    refused = await change(api, admin_headers, account(postgres_dsn, "meera"), disabled=True)

    assert (refused.status_code, refused.json()) == (409, {"detail": "own_account"})


async def test_the_last_enabled_admin_stays_an_admin(
    api: httpx.AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    postgres_dsn: str,
) -> None:
    meera = account(postgres_dsn, "meera")

    alone = await change(api, admin_headers, meera, role="member")
    await change(api, admin_headers, account(postgres_dsn, "reader"), role="admin")
    beside_another = await change(api, admin_headers, meera, role="member")

    assert (alone.status_code, alone.json()) == (409, {"detail": "last_admin"})
    assert (beside_another.status_code, beside_another.json()["role"]) == (200, "member")


async def test_a_password_reset_issues_a_temporary_password_and_ends_sessions(
    api: httpx.AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    postgres_dsn: str,
) -> None:
    reset = await api.post(
        f"/admin/users/{account(postgres_dsn, 'reader')}/password",
        headers=admin_headers | SAME_ORIGIN,
    )

    body = reset.json()
    session = await api.get("/session", headers=member_headers)
    signed_in = await api.post(
        "/auth/sign-in",
        json={"username": "reader", "password": body["temporary_password"]},
        headers=SAME_ORIGIN,
    )
    assert (reset.status_code, body["person"]["must_change_password"]) == (200, True)
    assert session.json()["detail"]["reason"] == "signed_out_elsewhere"
    assert (signed_in.status_code, signed_in.json()["must_change_password"]) == (200, True)
    assert await recorded(api, admin_headers) == [("password_reset", "Reader", {})]


async def test_an_account_the_api_does_not_hold_is_not_found(
    api: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    refused = await change(api, admin_headers, 999_999, role="admin")

    assert (refused.status_code, refused.json()) == (404, {"detail": "person_not_found"})


async def test_a_change_naming_nothing_is_refused(
    api: httpx.AsyncClient, admin_headers: dict[str, str], postgres_dsn: str
) -> None:
    assert (await change(api, admin_headers, account(postgres_dsn, "meera"))).status_code == 422


async def test_a_member_changes_no_account(
    api: httpx.AsyncClient, member_headers: dict[str, str], postgres_dsn: str
) -> None:
    refused = await change(api, member_headers, account(postgres_dsn, "reader"), role="admin")

    assert refused.status_code == 403
