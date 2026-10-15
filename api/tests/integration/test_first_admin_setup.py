"""The installation's first admin, created from the setup page while no admin exists."""

from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from api.main import create_app
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

COOKIE = "__Host-bitemporal_session"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
MEERA = {"username": "meera", "display_name": "Meera Iyer", "password": "a long first passphrase"}


@pytest.fixture
async def api(migrated_settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


async def set_up(api: httpx.AsyncClient, **changed: str) -> httpx.Response:
    return await api.post("/setup/admin", json=MEERA | changed, headers=SAME_ORIGIN)


def accounts(dsn: str) -> list[tuple[str, str]]:
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as connection:
        return connection.execute("select username, role from app_user order by id").fetchall()


async def test_the_first_admin_is_created_and_signed_in(
    api: httpx.AsyncClient, postgres_dsn: str
) -> None:
    before = (await api.get("/setup")).json()

    created = await set_up(api)

    session = await api.get("/session", headers={"Cookie": f"{COOKIE}={created.cookies[COOKIE]}"})
    assert before == {"admin_exists": False}
    assert created.status_code == 201
    assert (session.json()["username"], session.json()["role"]) == ("meera", "admin")
    assert session.json()["must_change_password"] is False
    assert (await api.get("/setup")).json() == {"admin_exists": True}


async def test_setup_is_refused_once_an_admin_exists(
    api: httpx.AsyncClient, postgres_dsn: str
) -> None:
    await set_up(api)

    second = await set_up(api, username="ravi", display_name="Ravi Kumar")

    assert (second.status_code, second.json()) == (409, {"detail": "admin_exists"})
    assert accounts(postgres_dsn) == [("meera", "admin")]


@pytest.mark.parametrize(
    ("password", "reason"),
    [("fourteen chars", "too_short"), ("meera's long passphrase", "contains_a_name")],
)
async def test_a_first_admin_the_password_rule_refuses_is_not_created(
    api: httpx.AsyncClient, postgres_dsn: str, password: str, reason: str
) -> None:
    refused = await set_up(api, password=password)

    assert (refused.status_code, refused.json()) == (422, {"detail": reason})
    assert accounts(postgres_dsn) == []
