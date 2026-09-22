"""Reading corporate actions a scrip code at a time, by invoking the asset with recorded responses."""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.corporate_actions import corporate_actions
from pipelines.resources import CorporateActions
from pipelines.sources.bse.corporate_actions import BseCorporateActions
from pipelines.sources.errors import SourceUnavailable
from pipelines.sources.registry import SourceDefinition

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "bse_corporate_actions"

RELIANCE = ("500325", "INE002A01018")
TATA_MOTORS = ("500570", "INE155A01022")
SHRIRAM_CODE = "511218"
SHRIRAM_OLD = "INE721A01013"
SHRIRAM_NEW = "INE721A01047"


class RecordedActions:
    """The real adapter and registry entry, answering from recorded responses in the order asked.

    A scrip code named unavailable stands for one the venue would not serve.
    """

    def __init__(self, unavailable: frozenset[str] = frozenset()) -> None:
        self._real = CorporateActions()
        self._unavailable = unavailable
        self.asked: list[str] = []

    def definition(self) -> SourceDefinition:
        return self._real.definition()

    def adapter(self) -> BseCorporateActions:
        adapter = self._real.adapter()

        def fetch(scrip_code: str) -> bytes:
            self.asked.append(scrip_code)
            if scrip_code in self._unavailable:
                raise SourceUnavailable(f"the venue did not serve {scrip_code}")
            return (CASSETTES / f"{scrip_code}.json").read_bytes()

        adapter.fetch = fetch  # type: ignore[method-assign]
        return adapter


@pytest.fixture
def database(migrated: Config, postgres_dsn: str) -> Iterator[PointedDatabase]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for isin in (RELIANCE[1], TATA_MOTORS[1], SHRIRAM_OLD, SHRIRAM_NEW):
            open_.execute(
                "insert into instrument_master (isin, name, country, instrument_type)"
                " values (%s, %s, 'IN', 'equity')",
                (isin, isin),
            )
        listings = [
            (RELIANCE[1], "RELIANCE", RELIANCE[0], "2024-01-01", None, None),
            (TATA_MOTORS[1], "TATAMOTORS", TATA_MOTORS[0], "2024-01-01", None, None),
            (SHRIRAM_OLD, "SHRIRAMFIN", SHRIRAM_CODE, "2024-01-01", "2025-01-09", "superseded"),
            (SHRIRAM_NEW, "SHRIRAMFIN", SHRIRAM_CODE, "2025-01-10", None, None),
        ]
        for isin, symbol, code, opened, closed, reason in listings:
            open_.execute(
                "insert into listing (isin, exchange, local_symbol, scrip_code, listing_date,"
                " delisting_date, closure_reason) values (%s, 'BSE', %s, %s, %s, %s, %s)",
                (isin, symbol, code, opened, closed, reason),
            )
        open_.execute(
            "insert into instrument_succession"
            " (predecessor_isin, exchange, successor_isin, changed_on)"
            " values (%s, 'BSE', %s, '2025-01-10')",
            (SHRIRAM_OLD, SHRIRAM_NEW),
        )
        open_.commit()

    yield PointedDatabase(dsn=postgres_dsn)

    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for table in (
            "corporate_action",
            "ingestion_log",
            "instrument_succession",
            "listing",
            "instrument_master",
        ):
            open_.execute(f"delete from {table}")
        open_.commit()


def rows(dsn: str, sql: str, params: tuple[str, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        return open_.execute(sql, params).fetchall()


def test_a_code_that_changed_face_value_is_read_first(database: PointedDatabase) -> None:
    """A series cannot be drawn across a split until the split is known."""
    recorded = RecordedActions()

    corporate_actions(build_asset_context(), database, recorded)

    assert recorded.asked[0] == SHRIRAM_CODE
    assert sorted(recorded.asked) == sorted([SHRIRAM_CODE, RELIANCE[0], TATA_MOTORS[0]])


def test_actions_are_recorded_against_the_isin_the_code_trades_under_now(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The split issued a new ISIN, and the history the venue returns belongs to the current one."""
    corporate_actions(build_asset_context(), database, RecordedActions())

    shriram = rows(
        postgres_dsn,
        "select distinct isin from corporate_action where isin in (%s, %s)",
        (SHRIRAM_OLD, SHRIRAM_NEW),
    )
    split = rows(
        postgres_dsn,
        "select ex_date from corporate_action where isin = %s and action_type = 'split'",
        (SHRIRAM_NEW,),
    )

    assert shriram == [(SHRIRAM_NEW,)]
    assert [str(ex_date) for (ex_date,) in split] == ["2025-01-10"]


def test_a_code_the_venue_will_not_serve_costs_that_code_alone(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A run over thousands of codes carries on past one it cannot read."""
    recorded = RecordedActions(unavailable=frozenset({TATA_MOTORS[0]}))

    result = corporate_actions(build_asset_context(), database, recorded)

    outcomes = dict(rows(postgres_dsn, "select outcome, count(*) from ingestion_log group by 1"))
    assert result.metadata["scrip_codes"] == 2
    assert result.metadata["failed"] == 1
    assert outcomes == {"succeeded": 2, "failed": 1}
