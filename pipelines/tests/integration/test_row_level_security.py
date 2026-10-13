"""Every table holding a person's rows keeps them to that person, as the schema's catalog shows."""

from collections.abc import Iterator

import psycopg
import pytest
from alembic.config import Config

from fixtures.database import MIGRATION_SCHEMA

# Tables with an owner_id column that row security does not hold to its owner: not enabled, not
# forced on the table's owner, or without a policy, which would leave the table empty to everyone.
UNGUARDED_TABLES = """
select tables.relname from pg_class as tables
inner join pg_namespace as schemas on schemas.oid = tables.relnamespace
inner join pg_attribute as columns
    on columns.attrelid = tables.oid and columns.attname = 'owner_id' and not columns.attisdropped
where schemas.nspname = %s and tables.relkind in ('r', 'p')
    and not (
        tables.relrowsecurity and tables.relforcerowsecurity
        and exists (select 1 from pg_policy where pg_policy.polrelid = tables.oid)
    )
order by 1
"""

# Views reading a table with an owner_id column with their owner's rights, which row security on
# the table does not bind.
OWNER_RIGHTS_VIEWS = """
select distinct views.relname from pg_class as views
inner join pg_namespace as schemas on schemas.oid = views.relnamespace
inner join pg_rewrite as rules on rules.ev_class = views.oid
inner join pg_depend as reads on reads.objid = rules.oid
inner join pg_attribute as columns
    on columns.attrelid = reads.refobjid and columns.attname = 'owner_id'
where schemas.nspname = %s and views.relkind = 'v'
    and not coalesce('security_invoker=true' = any(views.reloptions), false)
order by 1
"""

# Functions running with their owner's rights that resolve names through the caller's search path,
# where a caller's own objects could stand in for the schema's.
OPEN_PATH_DEFINERS = """
select functions.proname from pg_proc as functions
inner join pg_namespace as schemas on schemas.oid = functions.pronamespace
where schemas.nspname = %s and functions.prosecdef
    and not exists (
        select 1 from unnest(coalesce(functions.proconfig, '{}')) as setting
        where setting like 'search_path=%%'
    )
order by 1
"""


@pytest.fixture
def schema(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    """The migrated schema, in a transaction rolled back after the test."""
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as opened:
        yield opened
        opened.rollback()


def found(connection: psycopg.Connection, query: str) -> list[str]:
    return [row[0] for row in connection.execute(query, (MIGRATION_SCHEMA,)).fetchall()]


@pytest.mark.parametrize("query", [UNGUARDED_TABLES, OWNER_RIGHTS_VIEWS, OPEN_PATH_DEFINERS])
def test_the_migrated_schema_keeps_every_persons_rows_to_them(
    schema: psycopg.Connection, query: str
) -> None:
    assert found(schema, query) == []


def test_a_table_of_a_persons_rows_needs_forced_security_and_a_policy(
    schema: psycopg.Connection,
) -> None:
    schema.execute("create table notes (owner_id bigint)")
    assert found(schema, UNGUARDED_TABLES) == ["notes"]

    schema.execute("alter table notes enable row level security")
    schema.execute("alter table notes force row level security")
    assert found(schema, UNGUARDED_TABLES) == ["notes"]

    schema.execute("create policy own on notes using (owner_id = 1)")
    assert found(schema, UNGUARDED_TABLES) == []


def test_a_view_of_a_persons_rows_runs_as_its_reader(schema: psycopg.Connection) -> None:
    schema.execute("create view themes as select owner_id, theme from user_setting")
    assert found(schema, OWNER_RIGHTS_VIEWS) == ["themes"]

    schema.execute("alter view themes set (security_invoker = true)")
    assert found(schema, OWNER_RIGHTS_VIEWS) == []


def test_a_function_running_as_its_owner_fixes_its_search_path(
    schema: psycopg.Connection,
) -> None:
    schema.execute(
        "create function count_settings() returns bigint language sql security definer"
        " as $$ select count(*) from user_setting $$"
    )
    assert found(schema, OPEN_PATH_DEFINERS) == ["count_settings"]

    schema.execute(f"alter function count_settings() set search_path = {MIGRATION_SCHEMA}, pg_temp")
    assert found(schema, OPEN_PATH_DEFINERS) == []
