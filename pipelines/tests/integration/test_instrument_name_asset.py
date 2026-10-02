"""Naming instruments from BSE's list of scrips, by invoking the asset with recorded responses."""

from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.instrument_names import ingest_bse_names, ingest_nse_names
from pipelines.resources import NseLists, ScripLists
from pipelines.sources.bse.scrip_list import BseScripList
from pipelines.sources.errors import SourceUnavailable
from pipelines.sources.nse.equity_list import NseEquityList
from pipelines.sources.registry import SourceDefinition

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "bse_scrip_list"
NSE_CASSETTES = CASSETTES.parent / "nse_equity_list"
READ_ON = date(2026, 10, 2)
NEXT_DAY = READ_ON + timedelta(days=1)

RELIANCE = ("500325", "INE002A01018")
EMAMI = ("531162", "INE548C01032")
# Held here and named by no list.
UNLISTED = ("590099", "INE000A01011")


class RecordedScripLists:
    """The real adapter and registry entry, answering each status from its recorded response.

    A status in `refused` stands for one the venue would not serve, and `renamed` rewrites a name
    in the recorded answers, standing for a list read after a company changed its name.
    """

    def __init__(
        self, refused: frozenset[str] = frozenset(), renamed: dict[str, str] | None = None
    ) -> None:
        self._real = ScripLists()
        self._refused = refused
        self._renamed = renamed or {}

    def definition(self) -> SourceDefinition:
        return self._real.definition()

    def adapter(self) -> BseScripList:
        adapter = self._real.adapter()

        def fetch(status: str, collected_on: date) -> bytes:
            if status in self._refused:
                raise SourceUnavailable(f"the venue did not serve the {status} scrips")
            text = (CASSETTES / f"{status.lower()}.json").read_text()
            for before, after in self._renamed.items():
                text = text.replace(f'"{before}"', f'"{after}"')
            return text.encode()

        adapter.fetch = fetch  # type: ignore[method-assign]
        return adapter


class RecordedNseLists:
    """The real adapter and registry entry, answering each board from its recorded response."""

    def __init__(self, refused: frozenset[str] = frozenset()) -> None:
        self._real = NseLists()
        self._refused = refused

    def definition(self) -> SourceDefinition:
        return self._real.definition()

    def adapter(self) -> NseEquityList:
        adapter = self._real.adapter()

        def fetch(board: str, collected_on: date) -> bytes:
            if board in self._refused:
                raise SourceUnavailable(f"the venue did not serve the {board} board's list")
            return (NSE_CASSETTES / f"{board}.csv").read_bytes()

        adapter.fetch = fetch  # type: ignore[method-assign]
        return adapter


@pytest.fixture
def database(migrated: Config, postgres_dsn: str) -> PointedDatabase:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for code, isin in (RELIANCE, EMAMI, UNLISTED):
            open_.execute(
                "insert into instrument_master (isin, name, country, instrument_type)"
                " values (%s, %s, 'IN', 'equity')",
                (isin, code),
            )
            open_.execute(
                "insert into listing (isin, exchange, local_symbol, scrip_code, listing_date)"
                " values (%s, 'BSE', %s, %s, '2024-01-01')",
                (isin, code, code),
            )
        open_.commit()
    return PointedDatabase(dsn=postgres_dsn)


def rows(dsn: str, sql: str) -> list[tuple]:
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        return open_.execute(sql).fetchall()


def names(dsn: str) -> list[tuple]:
    return rows(dsn, "select isin, as_of_date, name from instrument_name order by isin, as_of_date")


def read(
    database: PointedDatabase, lists: RecordedScripLists, on: date = READ_ON
) -> dict[str, object]:
    result = ingest_bse_names(build_asset_context(), database, lists, on)
    return dict(result.metadata)


def test_an_instrument_held_is_named_as_the_latest_status_names_it(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Reliance's buy-back window is delisted as RILBBPH, and Emami's retired code as Emami Ltd."""
    counts = read(database, RecordedScripLists())

    assert names(postgres_dsn) == [
        (RELIANCE[1], READ_ON, "Reliance Industries Ltd"),
        (EMAMI[1], READ_ON, "Emami Ltd-$"),
    ]
    assert (counts["lists"], counts["failed"], counts["written"]) == (3, 0, 2)


def test_a_name_unchanged_since_the_last_read_is_not_written_again(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    read(database, RecordedScripLists())
    counts = read(database, RecordedScripLists(), NEXT_DAY)

    assert counts["written"] == 0
    assert [day for _, day, _ in names(postgres_dsn)] == [READ_ON, READ_ON]


def test_a_changed_name_is_written_beside_the_one_before(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    read(database, RecordedScripLists())
    renamed = RecordedScripLists(renamed={"Reliance Industries Ltd": "Reliance Industries Limited"})
    counts = read(database, renamed, NEXT_DAY)

    assert counts["written"] == 1
    assert [row for row in names(postgres_dsn) if row[0] == RELIANCE[1]] == [
        (RELIANCE[1], READ_ON, "Reliance Industries Ltd"),
        (RELIANCE[1], NEXT_DAY, "Reliance Industries Limited"),
    ]


def test_a_list_read_in_part_names_nothing(database: PointedDatabase, postgres_dsn: str) -> None:
    """Without the active scrips, Emami would be named as its retired code is."""
    counts = read(database, RecordedScripLists(refused=frozenset({"Active"})))

    assert names(postgres_dsn) == []
    assert (counts["lists"], counts["failed"]) == (2, 1)
    assert rows(
        postgres_dsn,
        "select partition_key, outcome from ingestion_log where source_id = 'bse_scrip_list'"
        " order by partition_key",
    ) == [
        ("active-20261002", "failed"),
        ("delisted-20261002", "succeeded"),
        ("suspended-20261002", "succeeded"),
    ]


def test_an_instrument_held_is_named_by_nses_lists_beside_bses(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    read(database, RecordedScripLists())
    result = ingest_nse_names(build_asset_context(), database, RecordedNseLists(), READ_ON)
    assert dict(result.metadata)["written"] == 2
    assert rows(
        postgres_dsn,
        "select isin, name from instrument_name where source_id = 'nse_equity_list' order by isin",
    ) == [(RELIANCE[1], "Reliance Industries Limited"), (EMAMI[1], "Emami Limited")]


def test_a_board_not_read_names_nothing(database: PointedDatabase, postgres_dsn: str) -> None:
    refused = RecordedNseLists(refused=frozenset({"sme"}))
    result = ingest_nse_names(build_asset_context(), database, refused, READ_ON)

    assert (dict(result.metadata)["failed"], names(postgres_dsn)) == (1, [])
