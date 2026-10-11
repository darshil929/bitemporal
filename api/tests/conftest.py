from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer

from api.config import ApiSettings
from api.main import create_app

# Matches the image the local stack runs, so tests exercise the same extensions.
POSTGRES_IMAGE = "timescale/timescaledb-ha:pg17"

# A schema the container starts without, holding no table.
EMPTY_SCHEMA = "fixture"

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container.get_connection_url()


def settings_for(dsn: str, schema: str) -> ApiSettings:
    """Settings naming the database outright, so no `.env` or variable can redirect them."""
    return ApiSettings(database_url=dsn, data_env=schema, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def empty_settings(postgres_dsn: str) -> ApiSettings:
    return settings_for(postgres_dsn, EMPTY_SCHEMA)


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
