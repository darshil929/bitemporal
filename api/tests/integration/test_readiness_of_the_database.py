from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest
from alembic import command
from alembic.config import Config

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
    start_api: StartApi, migrated_settings: ApiSettings, migrations: Config
) -> None:
    command.downgrade(migrations, "-1")
    try:
        async with start_api(migrated_settings) as api:
            response = await api.get("/ready")
    finally:
        command.upgrade(migrations, "head")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["migration"] not in (None, EXPECTED_REVISION)
    assert body["reason"] == (
        f"schema {migrated_settings.schema_name} is at migration {body['migration']},"
        f" the API expects {EXPECTED_REVISION}"
    )


async def test_a_schema_with_no_migration_record_is_not_ready(
    start_api: StartApi, empty_settings: ApiSettings
) -> None:
    async with start_api(empty_settings) as api:
        response = await api.get("/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == f"schema {empty_settings.schema_name} records no migration"


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
