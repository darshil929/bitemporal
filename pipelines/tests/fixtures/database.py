"""The databases every test package runs against, from one container per session.

The seed dataset fills the `fixture` schema once, with its models built and its daily features
computed as a flow leaves them. A test that migrates tables of its own uses the `dev` schema, migrated
to head before it and back to base after.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dagster import build_asset_context
from testcontainers.community.postgres import PostgresContainer

from fixtures.loader import load_seed
from pipelines.assets.features.daily import daily_features
from pipelines.assets.ingestion.registry import source_registry
from pipelines.resources import Database

# Matches the image the local stack runs, so tests exercise the same extensions.
POSTGRES_IMAGE = "timescale/timescaledb-ha:pg17"

PIPELINES_ROOT = Path(__file__).resolve().parents[2]
SEED_SCHEMA = "fixture"

# The seed dataset occupies the fixture schema in the same container.
MIGRATION_SCHEMA = "dev"


class PointedDatabase(Database):
    """The database resource, pointed at the schema a test built rather than the configured one."""

    dsn: str = ""
    schema: str = MIGRATION_SCHEMA

    def connect(self) -> psycopg.Connection:  # type: ignore[override]
        return psycopg.connect(self.dsn, options=f"-csearch_path={self.schema},public")


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
    """The seed dataset as a flow leaves it, for reading: sources registered, models built and
    daily features stored.

    Storing the features empties their table, which waits for every open transaction that read it;
    the connection returned holds one transaction for the whole session, so it opens afterwards.
    """
    source_registry(build_asset_context(), PointedDatabase(dsn=seeded_postgres, schema=SEED_SCHEMA))
    for arguments in (["seed"], ["run"]):
        subprocess.run(
            ["dbt", *arguments, "--profiles-dir", ".", "--target", SEED_SCHEMA],
            cwd=PIPELINES_ROOT / "dbt",
            env={**os.environ, **dbt_environment(seeded_postgres)},
            capture_output=True,
            check=True,
        )
    daily_features(database=PointedDatabase(dsn=seeded_postgres, schema=SEED_SCHEMA))
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
