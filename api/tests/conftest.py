from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import psycopg
import pytest
from alembic.config import Config

from api.config import ApiSettings
from api.main import create_app
from fixtures.database import MIGRATION_SCHEMA, SEED_SCHEMA

UNREACHABLE_DSN = "postgresql://nobody:nothing@127.0.0.1:1/nowhere"

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def settings_for(dsn: str, schema: str) -> ApiSettings:
    """Settings naming the database outright, so no `.env` or variable can redirect them."""
    return ApiSettings(database_url=dsn, data_env=schema, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def migrated_settings(migrated: Config, postgres_dsn: str) -> ApiSettings:
    """The API pointed at a schema migrated to head and holding no rows."""
    return settings_for(postgres_dsn, MIGRATION_SCHEMA)


@pytest.fixture
def dataset_settings(seeded_models: psycopg.Connection, seeded_postgres: str) -> ApiSettings:
    """The API pointed at the seed dataset, its models built and its daily features stored."""
    return settings_for(seeded_postgres, SEED_SCHEMA)


@pytest.fixture
def unreachable_settings() -> ApiSettings:
    return settings_for(UNREACHABLE_DSN, MIGRATION_SCHEMA)


@asynccontextmanager
async def running_api(settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


@pytest.fixture
def start_api() -> StartApi:
    """A client of the application started with the given settings, shut down on leaving."""
    return running_api
