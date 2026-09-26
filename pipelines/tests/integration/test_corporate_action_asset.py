"""Reading corporate actions a year of ex-dates at a time, by invoking the asset with recorded responses."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.corporate_actions import ingest_actions
from pipelines.facts import persist_actions
from pipelines.models.corporate_action import CorporateActionRecord
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

YEAR_2024 = (date(2024, 1, 1), date(2024, 12, 31))
YEAR_2025 = (date(2025, 1, 1), date(2025, 12, 31))
RECORDED = {
    YEAR_2024: "exdate-20240101-20241231.json",
    YEAR_2025: "exdate-20250101-20251231.json",
}
COLLECTED_ON = date(2026, 9, 25)


class RecordedActions:
    """The real adapter and registry entry, answering each range from the response recorded for it.

    A range the venue is answered for with another range's response stands for a file saved under
    the wrong name, and a range with no response for one the venue would not serve.
    """

    def __init__(self, served: dict[tuple[date, date], str] | None = None) -> None:
        self._real = CorporateActions()
        self._served = RECORDED if served is None else served
        self.asked: list[tuple[date, date]] = []

    def definition(self) -> SourceDefinition:
        return self._real.definition()

    def adapter(self) -> BseCorporateActions:
        adapter = self._real.adapter()

        def fetch(first: date, last: date, collected_on: date) -> bytes:
            self.asked.append((first, last))
            name = self._served.get((first, last))
            if name is None:
                raise SourceUnavailable(f"the venue did not serve {first} to {last}")
            return (CASSETTES / name).read_bytes()

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


def run(
    database: PointedDatabase, recorded: RecordedActions, *ranges: tuple[date, date]
) -> dict[str, object]:
    result = ingest_actions(build_asset_context(), database, recorded, list(ranges), COLLECTED_ON)
    return dict(result.metadata)


def test_one_answer_carries_the_actions_of_every_scrip_code(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A year of ex-dates is one request, not one per scrip code."""
    recorded = RecordedActions()

    run(database, recorded, YEAR_2024)

    stored = rows(postgres_dsn, "select distinct isin from corporate_action order by isin")
    bonus = rows(
        postgres_dsn,
        "select ex_date::text, ratio_from, ratio_to from corporate_action"
        " where isin = %s and action_type = 'bonus'",
        (RELIANCE[1],),
    )
    assert recorded.asked == [YEAR_2024]
    assert stored == [(RELIANCE[1],), (TATA_MOTORS[1],), (SHRIRAM_NEW,)]
    assert bonus == [("2024-10-28", Decimal(1), Decimal(2))]


def test_actions_are_recorded_against_the_isin_the_code_trades_under_now(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """The split issued a new ISIN, and the history the venue returns belongs to the current one."""
    run(database, RecordedActions(), YEAR_2025)

    shriram = rows(
        postgres_dsn,
        "select distinct isin from corporate_action where isin in (%s, %s)",
        (SHRIRAM_OLD, SHRIRAM_NEW),
    )
    split = rows(
        postgres_dsn,
        "select ex_date::text from corporate_action where isin = %s and action_type = 'split'",
        (SHRIRAM_NEW,),
    )
    assert shriram == [(SHRIRAM_NEW,)]
    assert split == [("2025-01-10",)]


def test_a_year_the_venue_will_not_serve_costs_that_year_alone(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    recorded = RecordedActions({YEAR_2025: RECORDED[YEAR_2025]})

    metadata = run(database, recorded, YEAR_2024, YEAR_2025)

    outcomes = dict(rows(postgres_dsn, "select outcome, count(*) from ingestion_log group by 1"))
    assert metadata["ranges"] == 1
    assert metadata["failed"] == 1
    assert outcomes == {"succeeded": 1, "failed": 1}


def test_an_answer_holding_ex_dates_outside_its_range_is_refused(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A file saved under the name of another year describes a range other than the one read."""
    recorded = RecordedActions({YEAR_2025: RECORDED[YEAR_2024]})

    metadata = run(database, recorded, YEAR_2025)

    assert metadata["failed"] == 1
    assert rows(postgres_dsn, "select count(*) from corporate_action")[0][0] == 0


def test_an_answer_lacking_an_action_already_stored_is_refused(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """A range the venue cut short reads the same as a year with fewer actions in it."""
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        persist_actions(
            open_,
            [
                CorporateActionRecord(
                    isin=RELIANCE[1],
                    action_type="dividend",
                    ex_date=date(2024, 3, 15),
                    source_id="bse_corporate_actions",
                    as_of_date=date(2026, 9, 22),
                    qualifier="interim",
                    dividend_amount=Decimal(5),
                )
            ],
        )
        open_.commit()

    metadata = run(database, RecordedActions(), YEAR_2024)

    logged = rows(postgres_dsn, "select outcome, detail from ingestion_log")
    assert metadata["failed"] == 1
    assert "lacks 1 actions already stored" in logged[0][1]
    assert rows(postgres_dsn, "select count(*) from corporate_action")[0][0] == 1


def test_an_action_read_again_with_the_same_terms_is_not_stored_again(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Re-reading a year on a later day adds no version where nothing about the action changed."""
    first = run(database, RecordedActions(), YEAR_2024)
    later = ingest_actions(
        build_asset_context(), database, RecordedActions(), [YEAR_2024], date(2026, 9, 26)
    )

    assert first["written"] == 7
    assert later.metadata["written"] == 0
