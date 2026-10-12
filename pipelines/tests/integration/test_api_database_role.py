"""The role the API connects as reads what the application shows and bypasses nothing."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fixtures.database import MIGRATION_SCHEMA, SEED_SCHEMA

ROLE = "bitemporal_api"


@contextmanager
def as_api(dsn: str, schema: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, options=f"-csearch_path={schema},public", autocommit=True) as opened:
        opened.execute(f"set role {ROLE}")
        yield opened


@pytest.fixture
def api(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with as_api(postgres_dsn, MIGRATION_SCHEMA) as connection:
        yield connection


def test_the_role_bypasses_nothing_and_owns_nothing(migrated: Config, postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls, rolcanlogin, rolcreaterole, rolcreatedb,"
            " (select count(*) from pg_class where relowner = pg_roles.oid)"
            " from pg_roles where rolname = %s",
            (ROLE,),
        ).fetchone()

    assert role == (False, False, True, False, False, 0)


@pytest.mark.parametrize("readable", ["mart_daily_features", "feature_release", "alembic_version"])
def test_the_role_reads_what_the_application_shows(api: psycopg.Connection, readable: str) -> None:
    assert api.execute(f"select count(*) from {readable}").fetchone() is not None


@pytest.mark.parametrize(
    "statement",
    [
        "select count(*) from price_daily",
        "select count(*) from daily_features_a",
        "insert into feature_release (table_name, row_count) values ('daily_features_b', 0)",
        "delete from feature_release",
    ],
)
def test_the_role_reaches_nothing_beneath(api: psycopg.Connection, statement: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        api.execute(statement)


def test_a_downgrade_keeps_the_role_and_drops_its_grants(
    migrated: Config, postgres_dsn: str
) -> None:
    command.downgrade(migrated, "0017")

    with psycopg.connect(postgres_dsn) as connection:
        kept = connection.execute(
            "select has_schema_privilege(%s, %s, 'usage') from pg_roles where rolname = %s",
            (ROLE, MIGRATION_SCHEMA, ROLE),
        ).fetchone()

    assert kept == (False,)


def test_the_role_reads_the_marts_and_not_the_models_beneath(
    seeded_models: psycopg.Connection, seeded_postgres: str
) -> None:
    with as_api(seeded_postgres, SEED_SCHEMA) as api:
        assert api.execute("select count(*) from mart_instruments").fetchone() != (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("select count(*) from stg_instruments")
