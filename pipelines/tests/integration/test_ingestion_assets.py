"""Ingesting one venue's day, by invoking the asset directly with a recorded response."""

import io
import zipfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import PartitionKeyRange, build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.bhavcopy import ingest
from pipelines.identity import isins_by_scrip_code
from pipelines.resources import Bhavcopies
from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.errors import MalformedRow, NotPublished
from pipelines.sources.nse.bhavcopy import NseBhavcopy
from pipelines.sources.registry import SourceDefinition

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
TRADE_DATE = "2026-08-14"


class RecordedBhavcopies:
    """The real adapters and registry entries, reading a recorded response rather than the venue.

    A venue mapped to None published nothing that day, which is what a holiday looks like, and
    a day named unreadable stands for one the venue published badly. A venue mapped to days serves
    each its own file.
    """

    def __init__(
        self,
        payloads: dict[str, bytes | dict[date, bytes] | None],
        unreadable: set[date] | None = None,
    ) -> None:
        self._payloads = payloads
        self._unreadable = unreadable or set()
        self._real = Bhavcopies()

    def definition(self, venue: str) -> SourceDefinition:
        return self._real.definition(venue)

    def adapter(self, venue: str) -> BseBhavcopy | NseBhavcopy:
        adapter = self._real.adapter(venue)
        recorded = self._payloads[venue]

        def fetch(partition: date, schema_version: str) -> bytes:
            if partition in self._unreadable:
                raise MalformedRow(f"{venue} published a file for {partition} that is not bars")
            served = recorded.get(partition) if isinstance(recorded, dict) else recorded
            if served is None:
                raise NotPublished(f"{venue} published nothing for {partition}")
            return served

        adapter.fetch = fetch  # type: ignore[method-assign]
        return adapter


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
    assert result.metadata["published"] == 1
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


def test_an_isin_on_two_lines_is_stored_from_its_ordinary_line(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """BSE lists Genus Power's T+0 line first on 16 June 2025, and it traded 24 shares."""
    bhavcopies = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20250616.csv")})

    result = ingest(build_asset_context(partition_key="2025-06-16"), "BSE", database, bhavcopies)

    stored = rows(postgres_dsn, "select scrip_code, local_symbol, volume from price_daily")
    named = rows(postgres_dsn, "select name from instrument_master")
    assert stored == [("530343", "GENUSPOWER", 112_827)]
    assert named == [("GENUS POWER INFRASTRUCTURES LT",)]
    assert result.metadata["secondary_lines"] == 1


SHORT_DAY = date(2022, 7, 15)


def store_bars(
    dsn: str, bars: list[tuple[str, str, str]], names: dict[str, str] | None = None
) -> None:
    """BSE bars as (scrip code, ISIN, trade date), each instrument under its name or its code."""
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for code, isin, day in bars:
            open_.execute(
                "insert into instrument_master (isin, name, country, instrument_type)"
                " values (%s, %s, 'IN', 'equity') on conflict do nothing",
                (isin, (names or {}).get(isin, code)),
            )
            open_.execute(
                "insert into price_daily (isin, venue, trade_date, as_of_date, open, high, low,"
                " close, volume, local_symbol, scrip_code)"
                " values (%s, 'BSE', %s, %s, 1, 1, 1, 1, 0, %s, %s)",
                (isin, day, day, code, code),
            )
        open_.commit()


def test_a_scrip_code_names_the_isin_of_its_nearest_stretch(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A code's first stored bar is the first day inside the recorded window, not the day it listed.

    A code whose stretches lie a day either side of the day and name different ISINs names none.
    The day's own stored bars came from an earlier read of it, and are not consulted.
    """
    store_bars(
        postgres_dsn,
        [
            ("531780", "INE229G01022", "2016-12-19"),
            ("531780", "INE229G01022", "2026-09-25"),
            ("541233", "INE970X01018", "2022-07-18"),
            ("599999", "INE999Z01011", "2022-07-14"),
            ("599999", "INE999Z01029", "2022-07-15"),
            ("599999", "INE999Z01029", "2022-07-16"),
            ("541276", "INE626Z01011", "2018-04-25"),
            ("541276", "INE626Z01011", "2023-06-02"),
            ("541276", "INE626Z01029", "2023-06-05"),
        ],
    )

    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        named = isins_by_scrip_code(connection, SHORT_DAY)

    assert named == {
        "531780": "INE229G01022",
        "541233": "INE970X01018",
        "541276": "INE626Z01011",
    }


def test_a_day_read_from_the_scrip_code_file_resolves_through_the_stored_bars(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """BSE's ISIN file for 15 July 2022 lacks 652 scrip codes, and its scrip code file lacks none.

    The file carries BSE's short names of the time, and the names already stored stand.
    """
    current = {
        "INE229G01022": "KAISER CORPORATION LIMITED",
        "INE970X01018": "Lemon Tree Hotels Limited",
        "INE783X01023": "Chemfab Alkalis Ltd",
        "INE626Z01011": "HARDWYN",
        "INE626Z01029": "HARDWYN INDIA LIMITED",
    }
    store_bars(
        postgres_dsn,
        [
            ("531780", "INE229G01022", "2022-07-14"),
            ("541233", "INE970X01018", "2022-07-18"),
            ("541269", "INE783X01023", "2022-07-14"),
            ("541269", "INE783X01023", "2022-07-18"),
            ("541276", "INE626Z01011", "2022-07-14"),
            ("541276", "INE626Z01029", "2023-06-05"),
        ],
        current,
    )
    bhavcopies = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20220715_scrip.zip")})

    result = ingest(build_asset_context(partition_key="2022-07-15"), "BSE", database, bhavcopies)

    stored = rows(
        postgres_dsn,
        "select scrip_code, isin from price_daily where trade_date = '2022-07-15'"
        " order by scrip_code",
    )
    logged = rows(postgres_dsn, "select schema_version from ingestion_log")
    names = dict(rows(postgres_dsn, "select isin, name from instrument_master"))
    assert stored == [
        ("531780", "INE229G01022"),
        ("541233", "INE970X01018"),
        ("541269", "INE783X01023"),
        ("541276", "INE626Z01011"),
    ]
    assert logged == [("bse_scrip",)]
    assert result.metadata["bars"] == 4
    assert names == current


def test_one_run_into_an_empty_database_reads_a_scrip_code_day(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A scrip code day loads in the same run as the days around it, on a database holding nothing.

    BSE answers its ISIN file for 13 December 2016 with its home page, and Interworld Digital did
    not trade on the 12th, so the day is read after the 14th, whose bars resolve its codes.
    """
    bhavcopies = RecordedBhavcopies(
        {
            "BSE": {
                date(2016, 12, 12): payload("bse_bhavcopy_equity", "20161212_legacy.csv"),
                date(2016, 12, 13): payload("bse_bhavcopy_equity", "20161213_scrip.csv"),
                date(2016, 12, 14): payload("bse_bhavcopy_equity", "20161214_legacy.csv"),
            }
        }
    )
    window = PartitionKeyRange(start="2016-12-12", end="2016-12-14")

    result = ingest(build_asset_context(partition_key_range=window), "BSE", database, bhavcopies)

    stored = rows(
        postgres_dsn,
        "select scrip_code, isin from price_daily where trade_date = '2016-12-13'"
        " order by scrip_code",
    )
    logged = rows(
        postgres_dsn,
        "select partition_key, schema_version, outcome from ingestion_log order by partition_key",
    )
    assert stored == [("500180", "INE040A01026"), ("532072", "INE177D01020")]
    assert logged == [
        ("2016-12-12", "bse_legacy", "succeeded"),
        ("2016-12-13", "bse_scrip", "succeeded"),
        ("2016-12-14", "bse_legacy", "succeeded"),
    ]
    assert result.metadata["failed"] == 0


def test_a_day_the_venue_never_published_stores_no_bars(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A holiday is an outcome the log carries, not a failure and not a gap."""
    bhavcopies = RecordedBhavcopies({"BSE": None})

    result = ingest(build_asset_context(partition_key="2026-08-17"), "BSE", database, bhavcopies)

    logged = rows(postgres_dsn, "select outcome, row_count from ingestion_log")
    assert result.metadata["unpublished"] == 1
    assert result.metadata["published"] == 0
    assert logged == [("not_published", None)]
    assert rows(postgres_dsn, "select count(*) from price_daily")[0][0] == 0


def test_the_legacy_format_is_read_for_a_day_before_the_cutover(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The registry picks the parser by trade date, so an old day reads its own format."""
    bhavcopies = RecordedBhavcopies(
        {"BSE": payload("bse_bhavcopy_equity", "20240115_legacy.csv.zip")}
    )

    result = ingest(build_asset_context(partition_key="2024-01-15"), "BSE", database, bhavcopies)

    logged = rows(postgres_dsn, "select schema_version from ingestion_log")
    assert logged == [("bse_legacy",)]
    assert result.metadata["bars"] > 0


def test_a_session_held_at_a_weekend_is_read(database: PointedDatabase, postgres_dsn: str) -> None:
    """NSE traded on Saturday 20 January 2024, and the day is stored like any other."""
    bhavcopies = RecordedBhavcopies(
        {"NSE": payload("nse_bhavcopy_equity", "20240120_legacy.csv.zip")}
    )

    result = ingest(build_asset_context(partition_key="2024-01-20"), "NSE", database, bhavcopies)

    stored = rows(postgres_dsn, "select distinct trade_date::text from price_daily")
    assert result.metadata["published"] == 1
    assert result.metadata["bars"] == 5
    assert stored == [("2024-01-20",)]


def test_a_run_covering_several_days_reads_each_of_them(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A run covers a range of days, reading the venue through one client and one session."""
    bhavcopies = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20260814.csv")})
    window = PartitionKeyRange(start="2026-08-10", end="2026-08-14")

    result = ingest(build_asset_context(partition_key_range=window), "BSE", database, bhavcopies)

    logged = rows(postgres_dsn, "select count(distinct partition_key) from ingestion_log")
    assert result.metadata["published"] == 5
    assert logged[0][0] == 5


def test_a_day_the_venue_published_badly_costs_that_day_alone(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The run carries on, and the day the venue published badly is recorded as failed."""
    bhavcopies = RecordedBhavcopies(
        {"BSE": payload("bse_bhavcopy_equity", "20260814.csv")}, unreadable={date(2026, 8, 12)}
    )
    window = PartitionKeyRange(start="2026-08-10", end="2026-08-14")

    result = ingest(build_asset_context(partition_key_range=window), "BSE", database, bhavcopies)

    outcomes = dict(
        rows(postgres_dsn, "select outcome, count(*) from ingestion_log group by outcome")
    )
    assert result.metadata["published"] == 4
    assert result.metadata["failed"] == 1
    assert outcomes == {"succeeded": 4, "failed": 1}
