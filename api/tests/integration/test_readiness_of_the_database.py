from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from api.config import ApiSettings
from api.services.readiness import EXPECTED_REVISION

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]


async def test_a_database_at_the_expected_migration_is_ready(
    start_api: StartApi, migrated_settings: ApiSettings
) -> None:
    async with start_api(migrated_settings) as api:
        response = await api.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database_schema": migrated_settings.schema_name,
        "migration": EXPECTED_REVISION,
        "expected_migration": EXPECTED_REVISION,
        "reason": None,
    }


async def test_a_database_behind_the_expected_migration_is_not_ready(
    start_api: StartApi, migrated_settings: ApiSettings, migrated: Config
) -> None:
    command.downgrade(migrated, "-1")
    try:
        async with start_api(migrated_settings) as api:
            response = await api.get("/ready")
    finally:
        command.upgrade(migrated, "head")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["migration"] not in (None, EXPECTED_REVISION)
    assert body["reason"] == (
        f"schema {migrated_settings.schema_name} is at migration {body['migration']},"
        f" the API expects {EXPECTED_REVISION}"
    )


async def test_a_schema_with_no_migration_record_is_not_ready(
    start_api: StartApi, migrated_settings: ApiSettings, migrated: Config, postgres_dsn: str
) -> None:
    schema = migrated_settings.schema_name
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("drop table {}.alembic_version").format(sql.Identifier(schema)))
    try:
        async with start_api(migrated_settings) as api:
            response = await api.get("/ready")
    finally:
        command.stamp(migrated, "head")

    assert response.status_code == 503
    assert response.json()["reason"] == f"schema {schema} records no migration"


async def test_a_database_that_does_not_answer_is_not_ready(
    start_api: StartApi, unreachable_settings: ApiSettings
) -> None:
    async with start_api(unreachable_settings) as api:
        response = await api.get("/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "the database does not answer"


async def test_the_service_reports_itself_up_without_its_database(
    start_api: StartApi, unreachable_settings: ApiSettings
) -> None:
    async with start_api(unreachable_settings) as api:
        response = await api.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
