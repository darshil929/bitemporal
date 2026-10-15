from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

import httpx
import psycopg
import pytest
from sqlalchemy import text

from api.config import ApiSettings
from api.db.database import Database
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]


class Abandoned(Exception):
    """Raised inside a transaction to end it."""


THEMES = text("select owner_id, theme from user_setting order by owner_id")
CHANGE_THEME = text("update user_setting set theme = :theme where owner_id = :owner")


@pytest.fixture
async def database(migrated_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(migrated_settings)
    yield opened
    await opened.close()


@pytest.fixture
def people(migrated_settings: ApiSettings, postgres_dsn: str) -> dict[str, int]:
    """Two accounts and their settings, written by the owner of the tables."""
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        accounts = {
            username: connection.execute(
                "insert into app_user (username, display_name, role, password_hash)"
                " values (%s, %s, 'member', 'unused') returning id",
                (username, username.title()),
            ).fetchone()[0]  # type: ignore[index]
            for username in ("asha", "ravi")
        }
        for username, theme in (("asha", "light"), ("ravi", "dark")):
            connection.execute(
                "insert into user_setting (owner_id, theme) values (%s, %s)",
                (accounts[username], theme),
            )
        connection.commit()
    return accounts


async def test_a_transaction_reads_the_environment_schema_first(database: Database) -> None:
    async with database.transaction() as session:
        current = (await session.execute(text("select current_schema()"))).scalar_one()
        schemas = (await session.execute(text("select current_schemas(false)"))).scalar_one()

    assert current == database.schema
    assert schemas == [database.schema, "public"]


@pytest.mark.parametrize(("person", "theme"), [("asha", "light"), ("ravi", "dark")])
async def test_a_transaction_for_a_person_reaches_their_rows_alone(
    database: Database, people: dict[str, int], person: str, theme: str
) -> None:
    async with database.transaction(people[person]) as session:
        themes = (await session.execute(THEMES)).all()

    assert themes == [(people[person], theme)]


async def test_a_transaction_for_no_one_reaches_no_person_s_rows(
    database: Database, people: dict[str, int]
) -> None:
    async with database.transaction() as session:
        themes = (await session.execute(THEMES)).all()

    assert themes == []


async def test_a_pooled_connection_carries_no_one_into_its_next_transaction(
    database: Database, people: dict[str, int]
) -> None:
    connection = text("select pg_backend_pid()")
    async with database.transaction(people["asha"]) as session:
        first = (await session.execute(connection)).scalar_one()

    async with database.transaction() as session:
        second = (await session.execute(connection)).scalar_one()
        acting_for = (
            await session.execute(text("select current_setting('app.user_id', true)"))
        ).scalar_one()
        themes = (await session.execute(THEMES)).all()

    assert second == first
    assert acting_for == ""
    assert themes == []


async def test_a_transaction_that_raises_writes_nothing(
    database: Database, people: dict[str, int]
) -> None:
    asha = people["asha"]
    with pytest.raises(Abandoned):
        async with database.transaction(asha) as session:
            await session.execute(CHANGE_THEME, {"theme": "dark", "owner": asha})
            raise Abandoned

    async with database.transaction(asha) as session:
        themes = (await session.execute(THEMES)).all()

    assert themes == [(asha, "light")]


async def test_a_transaction_that_ends_keeps_its_writes(
    database: Database, people: dict[str, int]
) -> None:
    asha = people["asha"]
    async with database.transaction(asha) as session:
        await session.execute(CHANGE_THEME, {"theme": "dark", "owner": asha})

    async with database.transaction(asha) as session:
        themes = (await session.execute(THEMES)).all()

    assert themes == [(asha, "dark")]


async def test_a_person_s_write_does_not_reach_another_s_row(
    database: Database, people: dict[str, int]
) -> None:
    async with database.transaction(people["ravi"]) as session:
        changed = await session.execute(CHANGE_THEME, {"theme": "dark", "owner": people["asha"]})

    assert changed.rowcount == 0  # type: ignore[attr-defined]


async def test_the_application_starts_and_serves_with_its_settings(
    start_api: StartApi, migrated_settings: ApiSettings
) -> None:
    async with start_api(migrated_settings) as api:
        response = await api.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
