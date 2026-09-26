"""Validating stored days, against the dataset and against a day built to fail."""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import psycopg
import pytest
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.completeness import trading_day_completeness
from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.checks.completeness import every_stored_day_has_a_verdict
from pipelines.facts import persist_bars
from pipelines.models.market import PriceBar

FIXTURE_SCHEMA = "fixture"

HDFC_BANK = "INE040A01034"
LIC_GOLD_ETF = "INF397L01554"


def bar(venue: str, close: str, trade_date: str = "2026-07-31", isin: str = HDFC_BANK) -> PriceBar:
    return PriceBar(
        isin=isin,
        venue=venue,
        trade_date=date.fromisoformat(trade_date),
        as_of_date=date.fromisoformat(trade_date),
        local_symbol="HDFCBANK",
        scrip_code="500180" if venue == "BSE" else None,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        previous_close=None,
        volume=1000,
        # Heavy enough at both venues for their prices to be compared.
        turnover=Decimal(100_000_000),
        trade_count=100,
    )


@pytest.fixture
def database(migrated: Config, postgres_dsn: str) -> Iterator[PointedDatabase]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        open_.execute(
            "insert into instrument_master (isin, name, country, instrument_type)"
            " values (%s, 'HDFC Bank Ltd', 'IN', 'equity') on conflict (isin) do nothing",
            (HDFC_BANK,),
        )
        open_.execute(
            "insert into instrument_master (isin, name, country, instrument_type)"
            " values (%s, 'LIC Gold ETF', 'IN', 'etf') on conflict (isin) do nothing",
            (LIC_GOLD_ETF,),
        )
        open_.commit()

    yield PointedDatabase(dsn=postgres_dsn)

    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for table in ("trading_day", "price_daily", "listing", "instrument_master"):
            open_.execute(f"delete from {table}")
        open_.commit()


def store(database: PointedDatabase, bars: list[PriceBar]) -> None:
    with database.connect() as connection:
        persist_bars(connection, bars)
        connection.commit()


def verdicts(database: PointedDatabase) -> list[tuple]:
    with database.connect() as connection:
        return connection.execute(
            "select venue, is_complete, divergent_instruments, detail from trading_day"
            " order by venue"
        ).fetchall()


def test_a_day_both_venues_agree_on_is_complete(database: PointedDatabase) -> None:
    store(database, [bar("BSE", "1900.00"), bar("NSE", "1900.40")])

    result = trading_day_completeness(build_asset_context(), database)

    assert result.metadata["venue_days_validated"] == 2
    assert [(venue, complete) for venue, complete, _, _ in verdicts(database)] == [
        ("BSE", True),
        ("NSE", True),
    ]


def test_venues_disagreeing_beyond_the_limit_leave_the_day_incomplete(
    database: PointedDatabase,
) -> None:
    """An action handled at one venue and not the other moves a price by thousands of points."""
    store(database, [bar("BSE", "1900.00"), bar("NSE", "950.00")])

    trading_day_completeness(build_asset_context(), database)
    stored = verdicts(database)

    assert [complete for _, complete, _, _ in stored] == [False, False]
    assert all(divergent == 1 for _, _, divergent, _ in stored)
    assert all("diverge" in (detail or "") for _, _, _, detail in stored)


def test_a_day_already_judged_is_not_judged_again(database: PointedDatabase) -> None:
    store(database, [bar("BSE", "1900.00"), bar("NSE", "1900.40")])

    trading_day_completeness(build_asset_context(), database)
    second = trading_day_completeness(build_asset_context(), database)

    assert second.metadata["venue_days_validated"] == 0
    assert len(verdicts(database)) == 2


def test_the_check_fails_while_a_day_carries_no_verdict(database: PointedDatabase) -> None:
    store(database, [bar("BSE", "1900.00")])

    before = every_stored_day_has_a_verdict(build_asset_context(), database)
    trading_day_completeness(build_asset_context(), database)
    after = every_stored_day_has_a_verdict(build_asset_context(), database)

    assert not before.passed
    assert before.metadata["venue_days_without_a_verdict"].value == 1
    assert after.passed


def test_a_day_whose_bars_grew_after_its_verdict_is_judged_again_on_that_day(
    database: PointedDatabase,
) -> None:
    """BSE's gold ETFs were read into the history after their days had been judged complete.

    LIC Gold ETF closed at 5,711.48 at BSE and 5,332.15 at NSE on 3 August 2020. A bar read later
    carries the day it describes as its as-of date, so the verdict drawn without it is restated,
    dated the day it was judged again, and the first stands for the dates before.
    """
    store(database, [bar("BSE", "1900.00"), bar("NSE", "1900.40")])
    trading_day_completeness(build_asset_context(), database)

    store(
        database,
        [bar("BSE", "5711.48", isin=LIC_GOLD_ETF), bar("NSE", "5332.15", isin=LIC_GOLD_ETF)],
    )
    result = trading_day_completeness(build_asset_context(), database)

    with database.connect() as connection:
        stored = connection.execute(
            "select venue, as_of_date, is_complete, bars from trading_day order by venue, as_of_date"
        ).fetchall()
    judged_on = datetime.now(VENUE_TIME).date()
    assert result.metadata["days_judged_again"] == 1
    assert stored == [
        ("BSE", date(2026, 7, 31), True, 1),
        ("BSE", judged_on, False, 2),
        ("NSE", date(2026, 7, 31), True, 1),
        ("NSE", judged_on, False, 2),
    ]
