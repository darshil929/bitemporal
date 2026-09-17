"""Ingesting one venue's day, by invoking the asset directly with a recorded response."""

import io
import zipfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA
from pipelines.assets.ingestion.bhavcopy import ingest
from pipelines.resources import Bhavcopies, Database
from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.errors import NotPublished
from pipelines.sources.nse.bhavcopy import NseBhavcopy
from pipelines.sources.registry import SourceDefinition

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
TRADE_DATE = "2026-08-14"


class RecordedBhavcopies:
    """The real adapters and registry entries, reading a recorded response rather than the venue.

    A venue mapped to None published nothing that day, which is what a holiday looks like.
    """

    def __init__(self, payloads: dict[str, bytes | None]) -> None:
        self._payloads = payloads
        self._real = Bhavcopies()

    def definition(self, venue: str) -> SourceDefinition:
        return self._real.definition(venue)

    def adapter(self, venue: str) -> BseBhavcopy | NseBhavcopy:
        adapter = self._real.adapter(venue)
        payload = self._payloads[venue]

        def fetch(partition: date, schema_version: str) -> bytes:
            if payload is None:
                raise NotPublished(f"{venue} published nothing for {partition}")
            return payload

        adapter.fetch = fetch  # type: ignore[method-assign]
        return adapter


class PointedDatabase(Database):
    """Connections to the schema the migrations under test built."""

    dsn: str = ""

    def connect(self):  # type: ignore[override]
        return psycopg.connect(self.dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public")


def payload(source_id: str, name: str) -> bytes:
    """The bytes an adapter's fetch returns: NSE unzips its archive before parsing."""
    recorded = (CASSETTES / source_id / name).read_bytes()
    if not name.endswith(".zip"):
        return recorded

    with zipfile.ZipFile(io.BytesIO(recorded)) as archive:
        entry = next(item for item in archive.namelist() if item.lower().endswith(".csv"))
        return archive.read(entry)


@pytest.fixture
def database(migrated: Config, postgres_dsn: str) -> Iterator[PointedDatabase]:
    yield PointedDatabase(dsn=postgres_dsn)

    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for table in ("price_daily", "ingestion_log", "listing", "instrument_master"):
            open_.execute(f"delete from {table}")
        open_.commit()


def rows(dsn: str, sql: str) -> list[tuple]:
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        return open_.execute(sql).fetchall()


def test_a_published_day_reaches_the_database(database: PointedDatabase, postgres_dsn: str) -> None:
    bhavcopies = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20260814.csv")})

    result = ingest(build_asset_context(partition_key=TRADE_DATE), "BSE", database, bhavcopies)

    stored = rows(postgres_dsn, "select count(*) from price_daily")[0][0]
    assert result.metadata["outcome"] == "succeeded"
    assert result.metadata["bars"] == stored
    assert stored > 0


def test_the_instruments_a_day_introduces_are_written_first(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Every fact references the instrument master, so a bar cannot land before its instrument."""
    bhavcopies = RecordedBhavcopies({"NSE": payload("nse_bhavcopy_equity", "20260814.csv.zip")})

    ingest(build_asset_context(partition_key=TRADE_DATE), "NSE", database, bhavcopies)

    orphans = rows(
        postgres_dsn,
        "select count(*) from price_daily p"
        " left join instrument_master i on i.isin = p.isin where i.isin is null",
    )
    assert orphans[0][0] == 0


def test_reading_the_same_day_twice_stores_it_once(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The phase closes on a partition that produces the same result however often it runs."""
    bhavcopies = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20260814.csv")})
    context = build_asset_context(partition_key=TRADE_DATE)

    first = ingest(context, "BSE", database, bhavcopies)
    second = ingest(context, "BSE", database, bhavcopies)

    stored = rows(postgres_dsn, "select count(*) from price_daily")[0][0]
    assert first.metadata["written"] == stored
    assert second.metadata["written"] == 0
    assert second.metadata["bars"] == first.metadata["bars"]


def test_a_day_the_venue_never_published_stores_no_bars(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A holiday is an outcome the log carries, not a failure and not a gap."""
    bhavcopies = RecordedBhavcopies({"BSE": None})

    result = ingest(build_asset_context(partition_key="2026-08-15"), "BSE", database, bhavcopies)

    logged = rows(postgres_dsn, "select outcome, row_count from ingestion_log")
    assert result.metadata["outcome"] == "not_published"
    assert logged == [("not_published", None)]
    assert rows(postgres_dsn, "select count(*) from price_daily")[0][0] == 0


def test_the_legacy_format_is_read_for_a_day_before_the_cutover(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The registry picks the parser by trade date, so an old day reads its own format."""
    bhavcopies = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20240115_legacy.csv")})

    result = ingest(build_asset_context(partition_key="2024-01-15"), "BSE", database, bhavcopies)

    assert result.metadata["schema_version"] == "bse_legacy"
    assert result.metadata["bars"] > 0
