"""The migrations build the identity and fact tables and enforce their invariants."""

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
FACT_TABLES = frozenset({"price_daily", "corporate_action", "ingestion_log"})
MANAGED_TABLES = IDENTITY_TABLES | FACT_TABLES

BAR_COLUMNS = "isin, venue, trade_date, as_of_date, open, high, low, close, volume"


@pytest.fixture
def migrated(postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    monkeypatch.setenv("DATABASE_URL", postgres_dsn)
    monkeypatch.setenv("DATA_ENV", MIGRATION_SCHEMA)

    config = Config(PIPELINES_ROOT / "alembic.ini")
    command.upgrade(config, "head")
    yield config
    command.downgrade(config, "base")


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public")


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


def _add_bar(
    connection: psycopg.Connection,
    isin: str,
    as_of_date: str,
    close: str,
    high: str = "110",
) -> None:
    connection.execute(
        f"insert into price_daily ({BAR_COLUMNS}) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (isin, "NSE", "2026-07-31", as_of_date, "100", high, "95", close, 1000),
    )


def test_upgrade_creates_every_managed_table(migrated: Config, postgres_dsn: str) -> None:
    assert MANAGED_TABLES <= _tables(postgres_dsn)


def test_migration_matches_the_model_definitions(migrated: Config) -> None:
    """Guards against the hand-written migration and the models drifting apart."""
    command.check(migrated)


def test_downgrade_removes_every_table_it_created(migrated: Config, postgres_dsn: str) -> None:
    command.downgrade(migrated, "base")
    assert not MANAGED_TABLES & _tables(postgres_dsn)


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


def test_price_daily_is_partitioned_on_trade_date(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        dimensions = connection.execute(
            "select column_name from timescaledb_information.dimensions"
            " where hypertable_schema = %s and hypertable_name = 'price_daily'",
            (MIGRATION_SCHEMA,),
        ).fetchall()

    assert [row[0] for row in dimensions] == ["trade_date"]


def test_a_republished_bar_is_stored_beside_the_original(
    migrated: Config, postgres_dsn: str
) -> None:
    """A correction must not destroy what the close was believed to be beforehand."""
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        _add_bar(connection, "INE002A01018", as_of_date="2026-07-31", close="105")
        _add_bar(connection, "INE002A01018", as_of_date="2026-08-01", close="108")

        known_on_the_day = connection.execute(
            "select distinct on (isin, venue, trade_date) close from price_daily"
            " where as_of_date <= %s"
            " order by isin, venue, trade_date, as_of_date desc",
            ("2026-07-31",),
        ).fetchone()
        known_later = connection.execute(
            "select distinct on (isin, venue, trade_date) close from price_daily"
            " where as_of_date <= %s"
            " order by isin, venue, trade_date, as_of_date desc",
            ("2026-08-02",),
        ).fetchone()

    assert known_on_the_day is not None and float(known_on_the_day[0]) == 105
    assert known_later is not None and float(known_later[0]) == 108


def test_a_price_bar_cannot_be_updated(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        _add_bar(connection, "INE002A01018", as_of_date="2026-07-31", close="105")

        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("update price_daily set close = 999")


def test_a_corporate_action_cannot_be_updated(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        connection.execute(
            "insert into corporate_action"
            " (isin, action_type, ex_date, source_id, as_of_date, ratio_from, ratio_to)"
            " values (%s, 'split', %s, %s, %s, 1, 5)",
            ("INE002A01018", "2026-06-01", "bse_corporate_actions", "2026-05-20"),
        )

        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("update corporate_action set ratio_to = 10")


def test_a_bar_whose_high_is_below_its_close_is_rejected(
    migrated: Config, postgres_dsn: str
) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            _add_bar(connection, "INE002A01018", as_of_date="2026-07-31", close="120", high="110")


def test_a_split_without_a_ratio_is_rejected(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into corporate_action"
                " (isin, action_type, ex_date, source_id, as_of_date)"
                " values (%s, 'split', %s, %s, %s)",
                ("INE002A01018", "2026-06-01", "bse_corporate_actions", "2026-05-20"),
            )
