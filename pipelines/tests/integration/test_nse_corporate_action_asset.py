"""Reading NSE corporate actions a year of ex-dates at a time, by invoking the asset with recorded responses."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.nse_corporate_actions import ingest_nse_actions
from pipelines.resources import NseActions
from pipelines.sources.errors import SourceUnavailable
from pipelines.sources.nse.corporate_actions import NseCorporateActions
from pipelines.sources.registry import SourceDefinition

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "nse_corporate_actions"

SHRIRAM_OLD, SHRIRAM_NEW = "INE721A01013", "INE721A01047"
HCL, ITC = "INE860A01027", "INE154A01025"
YEAR_2025 = (date(2025, 1, 1), date(2025, 12, 31))
YEAR_2024 = (date(2024, 1, 1), date(2024, 12, 31))
COLLECTED_ON = date(2026, 9, 26)


class RecordedActions:
    """The real adapter and registry entry, answering 2025 from NSE's recorded response."""

    def __init__(self) -> None:
        self._real = NseActions()

    def definition(self) -> SourceDefinition:
        return self._real.definition()

    def adapter(self) -> NseCorporateActions:
        adapter = self._real.adapter()

        def fetch(first: date, last: date, collected_on: date) -> bytes:
            if (first, last) != YEAR_2025:
                raise SourceUnavailable(f"the venue did not serve {first} to {last}")
            return (CASSETTES / "exdate-20250101-20251231.json").read_bytes()

        adapter.fetch = fetch  # type: ignore[method-assign]
        return adapter


@pytest.fixture
def database(migrated: Config, postgres_dsn: str) -> Iterator[PointedDatabase]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for isin in (SHRIRAM_OLD, SHRIRAM_NEW, HCL, ITC):
            open_.execute(
                "insert into instrument_master (isin, name, country, instrument_type)"
                " values (%s, %s, 'IN', 'equity')",
                (isin, isin),
            )
        open_.execute(
            "insert into instrument_succession"
            " (predecessor_isin, exchange, successor_isin, changed_on)"
            " values (%s, 'NSE', %s, '2025-01-10')",
            (SHRIRAM_OLD, SHRIRAM_NEW),
        )
        open_.commit()

    yield PointedDatabase(dsn=postgres_dsn)

    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for table in (
            "corporate_action",
            "ingestion_log",
            "instrument_succession",
            "instrument_master",
        ):
            open_.execute(f"delete from {table}")
        open_.commit()


def rows(dsn: str, sql: str) -> list[tuple]:
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        return open_.execute(sql).fetchall()


def test_an_action_filed_under_an_earlier_isin_is_recorded_under_its_successor(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """NSE filed Shriram Finance's split of 10 January 2025 under the ISIN the split retired."""
    ingest_nse_actions(
        build_asset_context(), database, RecordedActions(), [YEAR_2025], COLLECTED_ON
    )

    split = rows(
        postgres_dsn,
        "select isin, ex_date::text, ratio_from, ratio_to from corporate_action where action_type = 'split'",
    )
    assert split == [(SHRIRAM_NEW, "2025-01-10", Decimal(1), Decimal(5))]


def test_every_action_of_a_tracked_instrument_is_stored_and_the_rest_left_out(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    """Bajaj Finance and HDFC Bank are outside this universe; the InvIT row is outside the series."""
    ingest_nse_actions(
        build_asset_context(), database, RecordedActions(), [YEAR_2025], COLLECTED_ON
    )

    stored = rows(
        postgres_dsn,
        "select isin, action_type, qualifier, source_id from corporate_action order by isin, qualifier",
    )
    assert sorted(stored) == sorted(
        [
            (ITC, "unhandled", "demerger", "nse_corporate_actions"),
            (SHRIRAM_NEW, "split", "ordinary", "nse_corporate_actions"),
            (HCL, "dividend", "interim", "nse_corporate_actions"),
            (HCL, "dividend", "special", "nse_corporate_actions"),
        ]
    )


def test_a_year_the_venue_will_not_serve_costs_that_year_alone(
    database: PointedDatabase, postgres_dsn: str
) -> None:
    result = ingest_nse_actions(
        build_asset_context(), database, RecordedActions(), [YEAR_2024, YEAR_2025], COLLECTED_ON
    )

    outcomes = dict(rows(postgres_dsn, "select outcome, count(*) from ingestion_log group by 1"))
    assert result.metadata["ranges"] == 1
    assert outcomes == {"succeeded": 1, "failed": 1}
