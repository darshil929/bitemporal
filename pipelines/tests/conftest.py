import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from testcontainers.community.postgres import PostgresContainer

from fixtures.loader import load_seed
from pipelines.resources import Database

# Matches the image the local stack runs, so tests exercise the same extensions.
POSTGRES_IMAGE = "timescale/timescaledb-ha:pg17"

PIPELINES_ROOT = Path(__file__).resolve().parents[1]
DBT_SEEDS = PIPELINES_ROOT / "dbt" / "seeds"
SEED_SCHEMA = "fixture"

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


@pytest.fixture(scope="session")
def seeded_models(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    """A connection to the seed dataset with every model built over it."""
    for arguments in (["seed"], ["run"]):
        subprocess.run(
            ["dbt", *arguments, "--profiles-dir", ".", "--target", SEED_SCHEMA],
            cwd=PIPELINES_ROOT / "dbt",
            env={**os.environ, **dbt_environment(seeded_postgres)},
            capture_output=True,
            check=True,
        )
    with psycopg.connect(seeded_postgres, options=f"-csearch_path={SEED_SCHEMA},public") as opened:
        yield opened


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


def dbt_environment(dsn: str) -> dict[str, str]:
    """The variables dbt's profile reads, pointed at the test container."""
    url = urlsplit(dsn)
    return {
        "POSTGRES_HOST": url.hostname or "",
        "POSTGRES_PORT": str(url.port),
        "POSTGRES_USER": url.username or "",
        "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_DB": url.path.lstrip("/"),
    }


@pytest.fixture
def dbt_built(migrated: Config, postgres_dsn: str) -> Iterator[None]:
    """A migrated schema dbt builds into, cleared of the models and seeds before migrating down.

    The models are views over the migrated tables, which cannot be dropped while they stand.
    """
    yield
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        views = connection.execute(
            "select table_name from information_schema.views where table_schema = %s",
            (MIGRATION_SCHEMA,),
        ).fetchall()
        schema = sql.Identifier(MIGRATION_SCHEMA)
        for (view,) in views:
            connection.execute(
                sql.SQL("drop view if exists {}.{} cascade").format(schema, sql.Identifier(view))
            )
        for seed in DBT_SEEDS.glob("*.csv"):
            connection.execute(
                sql.SQL("drop table if exists {}.{}").format(schema, sql.Identifier(seed.stem))
            )
