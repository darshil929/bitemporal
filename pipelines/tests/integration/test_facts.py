"""Facts reach the database as appended rows, and a partition written twice reads the same."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import psycopg
import pytest
from alembic.config import Config

from conftest import MIGRATION_SCHEMA
from pipelines.facts import (
    persist_actions,
    persist_bars,
    persist_delivery,
    record_ingestion,
)
from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.models.market import DeliveryRecord, PriceBar

RELIANCE = "INE002A01018"
TATA_MOTORS_PV = "INE155A01022"


def bar(
    close: str = "1500.00", as_of: str = "2026-08-14", trade_date: str = "2026-08-14"
) -> PriceBar:
    return PriceBar(
        isin=RELIANCE,
        venue="NSE",
        trade_date=date.fromisoformat(trade_date),
        as_of_date=date.fromisoformat(as_of),
        local_symbol="RELIANCE",
        scrip_code=None,
        open=Decimal("1490.00"),
        high=Decimal("1510.00"),
        low=Decimal("1485.00"),
        close=Decimal(close),
        previous_close=Decimal("1495.00"),
        volume=1_200_000,
        turnover=Decimal("1800000000.00"),
        trade_count=42_000,
    )


def delivery(quantity: int = 600_000) -> DeliveryRecord:
    return DeliveryRecord(
        isin=RELIANCE,
        venue="NSE",
        trade_date=date(2026, 8, 14),
        as_of_date=date(2026, 8, 14),
        delivery_quantity=quantity,
    )


def spin_off(as_of: str = "2026-08-16") -> CorporateActionRecord:
    return CorporateActionRecord(
        isin=TATA_MOTORS_PV,
        action_type="unhandled",
        ex_date=date(2025, 10, 14),
        source_id="bse_corporate_actions",
        as_of_date=date.fromisoformat(as_of),
        qualifier="spin off",
        purpose="Spin Off",
    )


@pytest.fixture
def connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for isin in (RELIANCE, TATA_MOTORS_PV):
            open_.execute(
                "insert into instrument_master (isin, name, country, instrument_type)"
                " values (%s, %s, 'IN', 'equity') on conflict (isin) do nothing",
                (isin, "Test Instrument"),
            )
        yield open_
        open_.execute("delete from price_daily")
        open_.execute("delete from delivery_daily")
        open_.execute("delete from corporate_action")
        open_.execute("delete from ingestion_log")
        open_.commit()


def count(connection: psycopg.Connection, table: str) -> int:
    row = connection.execute(f"select count(*) from {table}").fetchone()
    assert row is not None
    return int(row[0])


def test_bars_are_written_once_however_often_the_day_is_read(
    connection: psycopg.Connection,
) -> None:
    """Re-running a partition has to produce the same result, which is the exit criterion."""
    assert persist_bars(connection, [bar()]) == 1
    assert persist_bars(connection, [bar()]) == 0
    assert count(connection, "price_daily") == 1


def test_a_republished_bar_lands_beside_the_version_it_corrects(
    connection: psycopg.Connection,
) -> None:
    persist_bars(connection, [bar(close="1500.00")])
    persist_bars(connection, [bar(close="1502.50", as_of="2026-08-18")])

    closes = connection.execute("select close from price_daily order by as_of_date").fetchall()

    assert [str(row[0]) for row in closes] == ["1500.0000", "1502.5000"]


def test_delivery_is_written_once(connection: psycopg.Connection) -> None:
    assert persist_delivery(connection, [delivery()]) == 1
    assert persist_delivery(connection, [delivery()]) == 0
    assert count(connection, "delivery_daily") == 1


def test_an_action_without_terms_keeps_its_text(connection: psycopg.Connection) -> None:
    assert persist_actions(connection, [spin_off()]) == 1

    row = connection.execute(
        "select purpose, ratio_from from corporate_action where action_type = 'unhandled'"
    ).fetchone()

    assert row == ("Spin Off", None)


def test_an_action_restated_later_is_appended(connection: psycopg.Connection) -> None:
    persist_actions(connection, [spin_off()])
    persist_actions(connection, [spin_off(as_of="2026-09-01")])

    assert count(connection, "corporate_action") == 2


def test_nothing_offered_writes_nothing(connection: psycopg.Connection) -> None:
    assert persist_bars(connection, []) == 0
    assert persist_delivery(connection, []) == 0
    assert persist_actions(connection, []) == 0


def test_a_day_a_venue_never_published_is_recorded_as_such(
    connection: psycopg.Connection,
) -> None:
    """A gap is read from the log afterwards, where an unpublished day and a failure differ."""
    record_ingestion(connection, "nse_bhavcopy_equity", "2026-08-15", "udiff", "not_published")
    record_ingestion(connection, "nse_bhavcopy_equity", "2026-08-14", "udiff", "succeeded", 2_100)

    outcomes = connection.execute(
        "select partition_key, outcome, row_count from ingestion_log order by partition_key"
    ).fetchall()

    assert outcomes == [("2026-08-14", "succeeded", 2_100), ("2026-08-15", "not_published", None)]
