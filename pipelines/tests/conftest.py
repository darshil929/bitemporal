from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from fixtures.loader import load_seed
from pipelines.resources import Database

# Matches the image the local stack runs, so tests exercise the same extensions.
POSTGRES_IMAGE = "timescale/timescaledb-ha:pg17"

PIPELINES_ROOT = Path(__file__).resolve().parents[1]

# The seed dataset occupies the fixture schema in the same container.
MIGRATION_SCHEMA = "dev"


class PointedDatabase(Database):
    """The database resource, pointed at the schema a test built rather than the configured one."""

    dsn: str = ""
    schema: str = MIGRATION_SCHEMA

    def connect(self) -> psycopg.Connection:  # type: ignore[override]
        return psycopg.connect(self.dsn, options=f"-csearch_path={self.schema},public")


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def seeded_postgres(postgres_dsn: str) -> str:
    load_seed(postgres_dsn)
    return postgres_dsn


@pytest.fixture
def migrated(postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    monkeypatch.setenv("DATABASE_URL", postgres_dsn)
    monkeypatch.setenv("DATA_ENV", MIGRATION_SCHEMA)

    config = Config(PIPELINES_ROOT / "alembic.ini")
    command.upgrade(config, "head")
    yield config
    command.downgrade(config, "base")


@pytest.fixture
def migrated_connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        yield connection
