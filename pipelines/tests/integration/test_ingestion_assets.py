"""Ingesting one venue's day, by invoking the asset directly with a recorded response."""

import io
import threading
import zipfile
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import PartitionKeyRange, build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.bhavcopy import ingest
from pipelines.assets.ingestion.completeness import record_verdicts
from pipelines.identity import INSTRUMENT_WRITES, isins_by_scrip_code
from pipelines.resources import Bhavcopies
from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.errors import MalformedRow, NotPublished
from pipelines.sources.nse.bhavcopy import NseBhavcopy
from pipelines.sources.registry import SourceDefinition

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
TRADE_DATE = "2026-08-14"
ABB = "INE117A01022"
ANSAL_PROPERTIES = "INE436A01026"


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
        corrections: dict[date, list[tuple[date, bytes]]] | None = None,
    ) -> None:
        self._payloads = payloads
        self._unreadable = unreadable or set()
        self._corrections = corrections or {}
        self._real = Bhavcopies()
        self.asked: list[date] = []
        self.rechecked: list[date] = []

    def definition(self, venue: str) -> SourceDefinition:
        return self._real.definition(venue)

    def adapter(self, venue: str) -> BseBhavcopy | NseBhavcopy:
        adapter = self._real.adapter(venue)
        recorded = self._payloads[venue]

        def fetch(partition: date, schema_version: str) -> bytes:
            self.asked.append(partition)
            if partition in self._unreadable:
                raise MalformedRow(f"{venue} published a file for {partition} that is not bars")
            served = recorded.get(partition) if isinstance(recorded, dict) else recorded
            if served is None:
                raise NotPublished(f"{venue} published nothing for {partition}")
            return served

        def recheck(partition: date, noticed_on: date) -> bytes | None:
            self.rechecked.append(partition)
            return None

        adapter.fetch = fetch  # type: ignore[method-assign]
        adapter.recheck = recheck  # type: ignore[method-assign]
        adapter.corrections = lambda partition: self._corrections.get(partition, [])  # type: ignore[method-assign]
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
    """An ISIN traded on two lines, its second listed first, is stored from its ordinary line."""
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
    """A day whose ISIN file lacks scrip codes is read whole from its scrip code file.

    That file carries the venue's short names, and the names already stored stand.
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

    A code that did not trade on the day before resolves through the day after, so the scrip code
    day is read after both.
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


def test_a_day_before_the_venue_is_covered_is_passed_over_without_a_request(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Every ingestion asset shares one calendar from 2011, and BSE is read from 12 December 2016."""
    bhavcopies = RecordedBhavcopies(
        {"BSE": {date(2016, 12, 12): payload("bse_bhavcopy_equity", "20161212_legacy.csv")}}
    )
    window = PartitionKeyRange(start="2016-12-10", end="2016-12-12")

    result = ingest(build_asset_context(partition_key_range=window), "BSE", database, bhavcopies)

    logged = rows(postgres_dsn, "select partition_key, outcome from ingestion_log")
    assert bhavcopies.asked == [date(2016, 12, 12)]
    assert logged == [("2016-12-12", "succeeded")]
    assert result.metadata["outside_coverage"] == 2
    assert result.metadata["published"] == 1


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
    """A session held at a weekend is stored like any other day."""
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


def name_of(dsn: str, isin: str) -> str:
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        found = open_.execute(
            "select name from instrument_master where isin = %s", (isin,)
        ).fetchone()
    assert found is not None
    return str(found[0])


def test_a_day_read_after_a_later_one_leaves_the_later_days_name(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A history bootstrap reads the recent years first and the older years in a second run.

    The name published on the later day stands, whichever day is read last.
    """
    recent = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20260814.csv")})
    older = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20240115_legacy.csv.zip")})

    ingest(build_asset_context(partition_key=TRADE_DATE), "BSE", database, recent)
    result = ingest(build_asset_context(partition_key="2024-01-15"), "BSE", database, older)

    assert name_of(postgres_dsn, ABB) == "ABB INDIA LIMITED"
    assert result.metadata["renamed"] == 0


@pytest.mark.parametrize("order", [("BSE", "NSE"), ("NSE", "BSE")])
def test_bses_name_stands_where_both_venues_traded_the_latest_day(
    database: PointedDatabase, postgres_dsn: str, order: tuple[str, str]
) -> None:
    """Where both venues traded on the latest day, BSE's name for the instrument stands."""
    bhavcopies = RecordedBhavcopies(
        {
            "BSE": payload("bse_bhavcopy_equity", "20260814.csv"),
            "NSE": payload("nse_bhavcopy_equity", "20260814.csv.zip"),
        }
    )

    for venue in order:
        ingest(build_asset_context(partition_key=TRADE_DATE), venue, database, bhavcopies)

    assert name_of(postgres_dsn, ANSAL_PROPERTIES) == "ANSAL PROPERTIES & INFRASTRUCT"


def test_the_name_of_the_latest_day_at_either_venue_stands(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The name published on the latest day at either venue stands."""
    nse = RecordedBhavcopies({"NSE": payload("nse_bhavcopy_equity", "20260814.csv.zip")})
    bse = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20240115_legacy.csv.zip")})

    ingest(build_asset_context(partition_key=TRADE_DATE), "NSE", database, nse)
    ingest(build_asset_context(partition_key="2024-01-15"), "BSE", database, bse)

    assert name_of(postgres_dsn, ANSAL_PROPERTIES) == "ANSAL PROP & INFRA LTD"


def test_a_venue_writes_its_day_only_in_its_turn(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Both venues' runs write the instrument master and the bars, so they write in turn.

    A chunk created for a new range of days locks the instrument master while the other venue's
    run can hold rows it has just inserted there, and the two deadlocked.
    """
    bhavcopies = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20260814.csv")})
    context = build_asset_context(partition_key=TRADE_DATE)
    writer = threading.Thread(target=ingest, args=(context, "BSE", database, bhavcopies))

    with psycopg.connect(postgres_dsn, autocommit=True) as other_venue:
        other_venue.execute("select pg_advisory_lock(%s)", (INSTRUMENT_WRITES,))
        writer.start()
        writer.join(timeout=2)
        waited = writer.is_alive()
        stored_while_waiting = rows(postgres_dsn, "select count(*) from price_daily")[0][0]
        other_venue.execute("select pg_advisory_unlock(%s)", (INSTRUMENT_WRITES,))
    writer.join(timeout=30)

    assert waited
    assert stored_while_waiting == 0
    assert rows(postgres_dsn, "select count(*) from price_daily")[0][0] > 0


def test_a_run_whose_every_day_failed_finishes_and_counts_them(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A run carries on past a venue that served nothing readable, and records every day it tried.

    Identity, delivery and the models read both venues, so a venue's run failing its step would
    stop them for the other venue too.
    """
    bhavcopies = RecordedBhavcopies(
        {"BSE": payload("bse_bhavcopy_equity", "20260814.csv")},
        unreadable={date(2026, 8, 13), date(2026, 8, 14)},
    )
    window = PartitionKeyRange(start="2026-08-13", end=TRADE_DATE)

    result = ingest(build_asset_context(partition_key_range=window), "BSE", database, bhavcopies)

    logged = rows(postgres_dsn, "select outcome, count(*) from ingestion_log group by outcome")
    assert result.metadata["failed"] == 2
    assert result.metadata["published"] == 0
    assert logged == [("failed", 2)]


DAY = date.fromisoformat(TRADE_DATE)
NOTICED_ON = date(2026, 8, 16)


def corrected_abb() -> bytes:
    """The recorded BSE file with one instrument's close changed, as a venue's corrected file."""
    original = payload("bse_bhavcopy_equity", "20260814.csv")
    return original.replace(b",7640.20,7645.00,7645.00,", b",7640.20,7650.00,7645.00,")


def abb_closes(dsn: str) -> list[tuple]:
    return rows(dsn, f"select as_of_date, close from price_daily where isin = '{ABB}' order by 1")


def test_a_corrected_file_stores_what_it_changed_dated_the_day_noticed(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    bhavcopies = RecordedBhavcopies(
        {"BSE": payload("bse_bhavcopy_equity", "20260814.csv")},
        corrections={DAY: [(NOTICED_ON, corrected_abb())]},
    )
    context = build_asset_context(partition_key=TRADE_DATE)

    first = ingest(context, "BSE", database, bhavcopies)
    again = ingest(context, "BSE", database, bhavcopies)

    assert (first.metadata["corrected"], again.metadata["corrected"]) == (1, 0)
    assert abb_closes(postgres_dsn) == [
        (DAY, Decimal("7645.0000")),
        (NOTICED_ON, Decimal("7650.0000")),
    ]


def test_a_sync_asks_again_for_the_days_already_held(database: PointedDatabase) -> None:
    """A day read for the first time in the run is not asked for twice; a bootstrap asks for none."""
    held = RecordedBhavcopies({"BSE": {DAY: payload("bse_bhavcopy_equity", "20260814.csv")}})
    ingest(build_asset_context(partition_key=TRADE_DATE), "BSE", database, held)
    window = build_asset_context(partition_key_range=PartitionKeyRange("2026-08-12", TRADE_DATE))

    ingest(window, "BSE", database, held)
    result = ingest(window, "BSE", database, held, recheck_on=NOTICED_ON)

    assert held.rechecked == [DAY]
    assert result.metadata["rechecked"] == 1
    assert result.metadata["recheck_failed"] == 0


def test_a_corrected_day_is_judged_again(database: PointedDatabase, postgres_dsn: str) -> None:
    original = RecordedBhavcopies({"BSE": payload("bse_bhavcopy_equity", "20260814.csv")})
    ingest(build_asset_context(partition_key=TRADE_DATE), "BSE", database, original)
    with database.connect() as connection:
        record_verdicts(connection, DAY)
        connection.commit()

    corrected = RecordedBhavcopies(
        {"BSE": payload("bse_bhavcopy_equity", "20260814.csv")},
        corrections={DAY: [(NOTICED_ON, corrected_abb())]},
    )
    ingest(build_asset_context(partition_key=TRADE_DATE), "BSE", database, corrected)
    with database.connect() as connection:
        record_verdicts(connection, NOTICED_ON)
        connection.commit()

    verdicts = rows(postgres_dsn, "select as_of_date from trading_day order by as_of_date")
    assert verdicts == [(DAY,), (NOTICED_ON,)]
