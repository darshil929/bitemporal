"""Reading delivery a trading day at a time, by invoking the asset with a recorded response."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import PartitionKeyRange, build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.delivery import ingest_delivery
from pipelines.facts import record_ingestion
from pipelines.resources import Deliveries
from pipelines.sources.bse.delivery import BseDelivery
from pipelines.sources.errors import NotPublished
from pipelines.sources.nse.delivery import FULL, POSITION, NseDelivery
from pipelines.sources.registry import SourceDefinition

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
TRADE_DATE = "2026-08-14"

# 20MICRONS traded under one ISIN to 13 August and under another from the 14th, keeping its ticker.
TICKER = "20MICRONS"
EARLIER_ISIN = "INE144J01019"
CURRENT_ISIN = "INE144J01027"


class RecordedDeliveries:
    """The real adapters and registry entries, reading a recorded response rather than the venue.

    A venue maps to one response for every day, or to a response per day. None, or a day it does
    not name, is a day the venue published nothing for. The position file is served only for the
    days named in `positions`.
    """

    def __init__(
        self,
        payloads: dict[str, bytes | dict[date, bytes] | None],
        positions: dict[date, bytes] | None = None,
    ) -> None:
        self._payloads = payloads
        self._positions = positions or {}
        self._real = Deliveries()
        self.asked: list[tuple[date, str]] = []

    def definition(self, venue: str) -> SourceDefinition:
        return self._real.definition(venue)

    def adapter(self, venue: str) -> BseDelivery | NseDelivery:
        adapter = self._real.adapter(venue)
        payload = self._payloads[venue]

        def fetch(partition: date, schema_version: str = FULL) -> bytes:
            self.asked.append((partition, schema_version))
            if schema_version == POSITION:
                served = self._positions.get(partition)
            else:
                served = payload.get(partition) if isinstance(payload, dict) else payload
            if served is None:
                raise NotPublished(f"{venue} published no {schema_version} for {partition}")
            return served

        adapter.fetch = fetch  # type: ignore[method-assign]
        return adapter


def recorded(venue_dir: str, name: str) -> bytes:
    return (CASSETTES / venue_dir / name).read_bytes()


def nse_day(written: str, delivered: int) -> bytes:
    """One NSE delivery row for the ticker, dated as the venue writes it."""
    header = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE,"
        " CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER"
    )
    row = (
        f"{TICKER}, EQ, {written}, 183.08, 182.28, 193.00, 182.00, 191.00, 190.90, 189.08,"
        f" 219809, 415.61, 4297, {delivered}, 49.8"
    )
    return f"{header}\n{row}\n".encode()


@pytest.fixture
def database(migrated: Config, postgres_dsn: str) -> Iterator[PointedDatabase]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for isin in (EARLIER_ISIN, CURRENT_ISIN):
            open_.execute(
                "insert into instrument_master (isin, name, country, instrument_type)"
                " values (%s, %s, 'IN', 'equity')",
                (isin, TICKER),
            )
        for isin, opened, closed, reason in (
            (EARLIER_ISIN, "2024-01-01", "2026-08-13", "superseded"),
            (CURRENT_ISIN, TRADE_DATE, None, None),
        ):
            open_.execute(
                "insert into listing (isin, exchange, local_symbol, scrip_code, listing_date,"
                " delisting_date, closure_reason) values (%s, 'NSE', %s, null, %s, %s, %s)",
                (isin, TICKER, opened, closed, reason),
            )
        open_.commit()

    yield PointedDatabase(dsn=postgres_dsn)

    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for table in ("delivery_daily", "ingestion_log", "listing", "instrument_master"):
            open_.execute(f"delete from {table}")
        open_.commit()


def rows(dsn: str, sql: str, params: tuple[str, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        return open_.execute(sql, params).fetchall()


def test_a_row_resolves_to_the_isin_in_force_on_its_trade_date(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The ticker carried the earlier ISIN to the 13th and the current one from the 14th.

    A map from ticker to ISIN that ignores dates holds only one of the two, so on one side of the
    change it places delivery against an instrument that was not trading under that name.
    """
    deliveries = RecordedDeliveries(
        {
            "NSE": {
                date(2026, 8, 13): nse_day("13-Aug-2026", 100_000),
                date(2026, 8, 14): nse_day("14-Aug-2026", 109_556),
            }
        }
    )
    window = PartitionKeyRange(start="2026-08-13", end=TRADE_DATE)

    ingest_delivery(build_asset_context(partition_key_range=window), "NSE", database, deliveries)

    stored = rows(
        postgres_dsn, "select trade_date::text, isin from delivery_daily order by trade_date"
    )
    assert stored == [("2026-08-13", EARLIER_ISIN), ("2026-08-14", CURRENT_ISIN)]


def test_a_row_naming_no_listing_that_day_is_left_out(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Only the one tracked ticker has a listing, so every other row in the file stays unresolved."""
    deliveries = RecordedDeliveries({"NSE": recorded("nse_delivery", "20260814.csv")})

    result = ingest_delivery(
        build_asset_context(partition_key=TRADE_DATE), "NSE", database, deliveries
    )

    assert result.metadata["written"] == 1
    assert rows(postgres_dsn, "select count(*) from delivery_daily")[0][0] == 1


def test_a_day_the_venue_published_no_delivery_for_is_recorded(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Delivery arrives hours after the prices and sometimes not at all."""
    deliveries = RecordedDeliveries({"NSE": None})

    result = ingest_delivery(
        build_asset_context(partition_key=TRADE_DATE), "NSE", database, deliveries
    )

    logged = rows(postgres_dsn, "select outcome from ingestion_log")
    assert result.metadata["unpublished"] == 1
    assert logged == [("not_published",)]


def test_a_day_without_a_session_answered_with_another_days_file_stores_nothing(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """NSE answers some days it held no session on with the delivery file of another day."""
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        record_ingestion(open_, "nse_bhavcopy_equity", "2026-08-15", "udiff", "not_published")
        open_.commit()
    deliveries = RecordedDeliveries({"NSE": {date(2026, 8, 15): nse_day("14-Aug-2026", 109_556)}})

    result = ingest_delivery(
        build_asset_context(partition_key="2026-08-15"), "NSE", database, deliveries
    )

    logged = rows(
        postgres_dsn, "select outcome from ingestion_log where source_id = 'nse_delivery'"
    )
    assert result.metadata["unpublished"] == 1
    assert logged == [("not_published",)]
    assert rows(postgres_dsn, "select count(*) from delivery_daily")[0][0] == 0
    assert deliveries.asked == [(date(2026, 8, 15), FULL)]


def test_a_trading_day_answered_with_another_days_file_fails_that_day_alone(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """NSE answered a request for 2019-09-30 with the file for 2019-06-27."""
    deliveries = RecordedDeliveries(
        {
            "NSE": {
                date(2026, 8, 13): nse_day("13-Aug-2026", 100_000),
                date(2026, 8, 14): nse_day("13-Aug-2026", 100_000),
            }
        }
    )
    window = PartitionKeyRange(start="2026-08-13", end=TRADE_DATE)

    result = ingest_delivery(
        build_asset_context(partition_key_range=window), "NSE", database, deliveries
    )

    stored = rows(postgres_dsn, "select trade_date::text from delivery_daily")
    logged = rows(
        postgres_dsn,
        "select partition_key, outcome from ingestion_log order by partition_key",
    )
    assert result.metadata["failed"] == 1
    assert stored == [("2026-08-13",)]
    assert logged == [("2026-08-13", "succeeded"), ("2026-08-14", "failed")]


def test_a_trading_day_the_full_file_does_not_answer_is_read_from_the_position_file(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """NSE publishes the same figures in its security-wise delivery position file."""
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        record_ingestion(open_, "nse_bhavcopy_equity", TRADE_DATE, "udiff", "succeeded", 1)
        open_.commit()
    deliveries = RecordedDeliveries(
        {"NSE": {date(2026, 8, 14): nse_day("13-Aug-2026", 100_000)}},
        positions={date(2026, 8, 14): recorded("nse_delivery", "MTO_14082026.DAT")},
    )

    result = ingest_delivery(
        build_asset_context(partition_key=TRADE_DATE), "NSE", database, deliveries
    )

    stored = rows(
        postgres_dsn, "select trade_date::text, isin, delivery_quantity from delivery_daily"
    )
    logged = rows(
        postgres_dsn,
        "select schema_version, outcome from ingestion_log where source_id = 'nse_delivery'",
    )
    assert result.metadata["published"] == 1
    assert stored == [(TRADE_DATE, CURRENT_ISIN, 109_556)]
    assert logged == [("mto", "succeeded")]
