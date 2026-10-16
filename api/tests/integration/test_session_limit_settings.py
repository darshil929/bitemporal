"""The session limits an admin sets for everyone, each change recorded and in force at once."""

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
# The reader's session was last used 61 minutes ago.
QUIET_FOR_AN_HOUR = (
    "update app_session set last_seen_at = now() - interval '61 minutes' where owner_id ="
    " (select id from app_user where username = 'reader')"
)


@pytest.fixture
async def api(migrated_settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


async def change(api: httpx.AsyncClient, headers: dict[str, str], **limits: Any) -> httpx.Response:
    return await api.patch("/admin/settings", json=limits, headers=headers | SAME_ORIGIN)


async def recorded(api: httpx.AsyncClient, headers: dict[str, str]) -> list[tuple[Any, ...]]:
    entries = (await api.get("/admin/audit", headers=headers)).json()
    return [(entry["action"], entry["detail"]) for entry in entries]


async def test_the_limits_start_at_two_hours_idle_and_twelve_at_most(
    api: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    limits = (await api.get("/admin/settings", headers=admin_headers)).json()

    assert (limits["session_idle_minutes"], limits["session_max_hours"]) == (120, 12)


async def test_a_shorter_idle_limit_is_recorded_and_ends_a_session_quiet_for_longer(
    api: httpx.AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    postgres_dsn: str,
) -> None:
    changed = await change(api, admin_headers, session_idle_minutes=60)
    options = f"-csearch_path={MIGRATION_SCHEMA},public"
    with psycopg.connect(postgres_dsn, options=options, autocommit=True) as owner:
        owner.execute(QUIET_FOR_AN_HOUR)

    session = await api.get("/session", headers=member_headers)

    assert (changed.json()["session_idle_minutes"], changed.json()["session_max_hours"]) == (60, 12)
    assert (session.status_code, session.json()["detail"]["reason"]) == (401, "idle")
    assert session.json()["detail"]["idle_minutes"] == 60
    assert await recorded(api, admin_headers) == [
        ("session_limits_changed", {"idle_minutes": {"from": 120, "to": 60}})
    ]


async def test_a_limit_already_in_force_changes_nothing(
    api: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    unchanged = await change(api, admin_headers, session_max_hours=12)

    assert unchanged.status_code == 200
    assert await recorded(api, admin_headers) == []


@pytest.mark.parametrize(
    "limits",
    [{"session_idle_minutes": 4}, {"session_max_hours": 73}, {}],
)
async def test_a_limit_out_of_range_or_none_at_all_is_refused(
    api: httpx.AsyncClient, admin_headers: dict[str, str], limits: dict[str, int]
) -> None:
    assert (await change(api, admin_headers, **limits)).status_code == 422


async def test_a_member_sets_no_limit(
    api: httpx.AsyncClient, member_headers: dict[str, str]
) -> None:
    refused = [
        await api.get("/admin/settings", headers=member_headers),
        await change(api, member_headers, session_idle_minutes=60),
    ]

    assert [response.status_code for response in refused] == [403, 403]
