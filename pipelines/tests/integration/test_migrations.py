"""The baseline migration builds the identity tables and enforces their invariants."""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

PIPELINES_ROOT = Path(__file__).resolve().parents[2]

# The seed dataset occupies the fixture schema in the same container.
MIGRATION_SCHEMA = "dev"

IDENTITY_TABLES = frozenset(
    {"instrument_master", "listing", "listing_suspension", "instrument_primary_venue"}
)


@pytest.fixture
def migrated(postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    monkeypatch.setenv("DATABASE_URL", postgres_dsn)
    monkeypatch.setenv("DATA_ENV", MIGRATION_SCHEMA)

    config = Config(PIPELINES_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(PIPELINES_ROOT / "src/pipelines/db/migrations"))

    command.upgrade(config, "head")
    yield config
    command.downgrade(config, "base")


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA}")


def _tables(dsn: str) -> set[str]:
    with _connect(dsn) as connection:
        rows = connection.execute(
            "select table_name from information_schema.tables where table_schema = %s",
            (MIGRATION_SCHEMA,),
        ).fetchall()
    return {str(row[0]) for row in rows}


def _add_instrument(connection: psycopg.Connection, isin: str) -> None:
    connection.execute(
        "insert into instrument_master (isin, name, country, instrument_type)"
        " values (%s, %s, %s, %s)",
        (isin, "Test Instrument", "IN", "equity"),
    )


def test_upgrade_creates_the_identity_tables(migrated: Config, postgres_dsn: str) -> None:
    assert IDENTITY_TABLES <= _tables(postgres_dsn)


def test_migration_matches_the_model_definitions(migrated: Config) -> None:
    """Guards against the hand-written migration and the models drifting apart."""
    command.check(migrated)


def test_downgrade_removes_every_table_it_created(migrated: Config, postgres_dsn: str) -> None:
    command.downgrade(migrated, "base")
    assert not IDENTITY_TABLES & _tables(postgres_dsn)


def test_an_isin_that_is_not_an_isin_is_rejected(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        _add_instrument(connection, "RELIANCE")


def test_a_closed_listing_must_say_why_it_closed(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into listing"
                " (isin, exchange, local_symbol, listing_date, delisting_date)"
                " values (%s, %s, %s, %s, %s)",
                ("INE002A01018", "NSE", "RELIANCE", "2020-01-01", "2024-01-01"),
            )


def test_a_rename_keeps_the_superseded_symbol(migrated: Config, postgres_dsn: str) -> None:
    """The symbol in force on a past date has to stay recoverable after a rename."""
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE009A01021")
        connection.execute(
            "insert into listing"
            " (isin, exchange, local_symbol, listing_date, delisting_date, closure_reason)"
            " values (%s, %s, %s, %s, %s, %s)",
            ("INE009A01021", "NSE", "INFOSYSTCH", "2000-01-01", "2011-06-16", "renamed"),
        )
        connection.execute(
            "insert into listing (isin, exchange, local_symbol, listing_date)"
            " values (%s, %s, %s, %s)",
            ("INE009A01021", "NSE", "INFY", "2011-06-17"),
        )

        symbols = connection.execute(
            "select local_symbol from listing where listing_date <= %s"
            " and (delisting_date is null or delisting_date >= %s)",
            ("2010-01-01", "2010-01-01"),
        ).fetchall()

    assert [row[0] for row in symbols] == ["INFOSYSTCH"]
