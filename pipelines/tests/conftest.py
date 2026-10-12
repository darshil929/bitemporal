from collections.abc import Iterator

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql

from fixtures.database import MIGRATION_SCHEMA
from pipelines.db.schema import Base


@pytest.fixture
def migrated_connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        yield connection


@pytest.fixture
def dbt_built(migrated: Config, postgres_dsn: str) -> Iterator[None]:
    """A migrated schema dbt builds into, cleared of the models and seeds before migrating down.

    The models are views and tables over the migrated tables, which cannot be dropped while views
    stand on them. Every table the migrations do not manage is one dbt built.
    """
    yield
    managed = set(Base.metadata.tables) | {"alembic_version"}
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
        tables = connection.execute(
            "select table_name from information_schema.tables"
            " where table_schema = %s and table_type = 'BASE TABLE'",
            (MIGRATION_SCHEMA,),
        ).fetchall()
        for (table,) in tables:
            if table not in managed:
                connection.execute(
                    sql.SQL("drop table {}.{}").format(schema, sql.Identifier(table))
                )
