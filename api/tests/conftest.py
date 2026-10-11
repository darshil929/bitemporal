from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from api.config import ApiSettings
from api.main import create_app

# Matches the image the local stack runs, so tests exercise the same extensions.
POSTGRES_IMAGE = "timescale/timescaledb-ha:pg17"

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "pipelines" / "alembic.ini"

# A schema the container starts without, holding no table.
EMPTY_SCHEMA = "fixture"
# The schema the migrations build.
MIGRATED_SCHEMA = "dev"

UNREACHABLE_DSN = "postgresql://nobody:nothing@127.0.0.1:1/nowhere"

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


@pytest.fixture
def migrations(postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    """Alembic aimed at the container's migrated schema, migrated to head and back to base after."""
    monkeypatch.setenv("DATABASE_URL", postgres_dsn)
    monkeypatch.setenv("DATA_ENV", MIGRATED_SCHEMA)
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    yield config
    command.downgrade(config, "base")


@pytest.fixture
def migrated_settings(migrations: Config, postgres_dsn: str) -> ApiSettings:
    return settings_for(postgres_dsn, MIGRATED_SCHEMA)


@pytest.fixture
def unreachable_settings() -> ApiSettings:
    return settings_for(UNREACHABLE_DSN, MIGRATED_SCHEMA)


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
