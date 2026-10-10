"""The rules every stored daily feature row has to satisfy."""

from collections.abc import Iterator

import psycopg
import pytest
from alembic.config import Config

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.checks.features import RULES, daily_feature_ranges

HDFC_BANK = "INE040A01034"

ROW = {
    "isin": HDFC_BANK,
    "trade_date": "2025-12-31",
    "as_of_date": "2025-12-31",
    "primary_venue": "NSE",
    "close": 991.2,
    "rsi_14": 48.3,
    "volatility_20d": 0.18,
    "adtv_20d": 1.5e10,
    "volume_ratio_20d": 1.1,
    "delivery_pct_1d": 64.2,
    "delivery_pct_20d": 58.0,
    "from_52w_high": -0.03,
    "sma_20": 993.0,
    "sma_50": 995.5,
    "sma_200": 970.0,
    "ema_20": 993.0,
    "ema_50": 990.0,
    "bollinger_20_upper": 1010.0,
    "bollinger_20_lower": 976.0,
    "is_day_complete": True,
    "is_diverging": False,
}

BREAKING = {
    "rsi_runs_from_0_to_100": "rsi_14 = 101",
    "no_quantity_is_negative": "adtv_20d = -1",
    "delivery_stays_within_volume": "delivery_pct_1d = 120",
    "the_bands_hold_the_average": "bollinger_20_lower = 1000",
    "the_close_sits_at_or_below_the_52_week_high": "from_52w_high = 0.01",
    "averages_are_positive": "sma_200 = 0",
    "a_diverging_day_is_incomplete": "is_diverging = true",
}


@pytest.fixture
def connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        open_.execute(
            "insert into instrument_master (isin, name, country, instrument_type)"
            " values (%s, 'HDFC Bank', 'IN', 'equity')",
            (HDFC_BANK,),
        )
        open_.execute(
            "create table venue_delivery_discrepancies"
            " (venue varchar(12), trade_date date, reason text)"
        )
        columns = ", ".join(ROW)
        open_.execute(
            f"insert into mart_daily_features ({columns}) values ({', '.join(['%s'] * len(ROW))})",
            tuple(ROW.values()),
        )
        open_.commit()
        yield open_
        open_.rollback()
        open_.execute("drop table venue_delivery_discrepancies")
        open_.execute("delete from mart_daily_features")
        open_.commit()


def outcomes(postgres_dsn: str) -> dict[str, tuple[bool, int]]:
    return {
        result.check_name: (result.passed, result.metadata["rows_breaking"].value)
        for result in daily_feature_ranges(database=PointedDatabase(dsn=postgres_dsn))
    }


def test_every_rule_holds_for_a_row_within_range(
    connection: psycopg.Connection, postgres_dsn: str
) -> None:
    assert outcomes(postgres_dsn) == {name: (True, 0) for name in RULES}


@pytest.mark.parametrize("rule", sorted(BREAKING))
def test_a_row_breaking_a_rule_fails_that_rule_alone(
    connection: psycopg.Connection, postgres_dsn: str, rule: str
) -> None:
    connection.execute(f"update mart_daily_features set {BREAKING[rule]}")
    connection.commit()

    failed = {name for name, (passed, _) in outcomes(postgres_dsn).items() if not passed}

    assert failed == {rule}
    assert outcomes(postgres_dsn)[rule] == (False, 1)


def test_delivery_above_volume_passes_on_a_reviewed_venue_day(
    connection: psycopg.Connection, postgres_dsn: str
) -> None:
    connection.execute("update mart_daily_features set delivery_pct_1d = 120")
    connection.execute(
        "insert into venue_delivery_discrepancies values ('NSE', '2025-12-31', 'reviewed')"
    )
    connection.commit()

    assert outcomes(postgres_dsn)["delivery_stays_within_volume"] == (True, 0)
