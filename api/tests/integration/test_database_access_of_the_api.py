from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest
from sqlalchemy import text

from api.config import ApiSettings
from api.db.database import Database

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]


class Abandoned(Exception):
    """Raised inside a transaction to end it."""


@pytest.fixture
async def database(empty_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(empty_settings)
    yield opened
    await opened.close()


async def test_a_transaction_reads_the_environment_schema_first(database: Database) -> None:
    async with database.transaction() as session:
        await session.execute(text("create schema if not exists fixture"))
        current = (await session.execute(text("select current_schema()"))).scalar_one()
        schemas = (await session.execute(text("select current_schemas(false)"))).scalar_one()

    assert current == database.schema
    assert schemas == [database.schema, "public"]


async def test_a_transaction_that_raises_writes_nothing(database: Database) -> None:
    with pytest.raises(Abandoned):
        async with database.transaction() as session:
            await session.execute(text("create schema if not exists fixture"))
            await session.execute(text("create table abandoned_marker (id integer)"))
            raise Abandoned

    async with database.transaction() as session:
        found = (await session.execute(text("select to_regclass('abandoned_marker')"))).scalar()

    assert found is None


async def test_a_transaction_that_ends_keeps_its_writes(database: Database) -> None:
    async with database.transaction() as session:
        await session.execute(text("create schema if not exists fixture"))
        await session.execute(text("create table kept_marker (id integer)"))

    async with database.transaction() as session:
        found = (await session.execute(text("select to_regclass('kept_marker')"))).scalar()
        await session.execute(text("drop table kept_marker"))

    assert found == "kept_marker"


async def test_the_application_starts_and_serves_with_its_settings(
    start_api: StartApi, empty_settings: ApiSettings
) -> None:
    async with start_api(empty_settings) as api:
        response = await api.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
