"""The daily features are stored a computation at a time, each replacing every stored row."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from decimal import Decimal

import numpy as np
import psycopg
import pytest
from alembic.config import Config

from conftest import MIGRATION_SCHEMA
from pipelines.daily_features import (
    ENGINE_COLUMNS,
    DailyFeatureRows,
    FeatureWriteRefused,
    replace_daily_features,
)

RELIANCE = "INE002A01018"
HDFC_BANK = "INE040A01034"


def feature_rows(isins: list[str], days: list[str], rsi: float = 50.0) -> DailyFeatureRows:
    count = len(isins)
    figures = np.full((len(ENGINE_COLUMNS), count), 0.25)
    figures[ENGINE_COLUMNS.index("rsi_14")] = rsi
    figures[ENGINE_COLUMNS.index("return_1y")] = np.nan
    figures[ENGINE_COLUMNS.index("is_52w_high")] = 1.0
    figures[ENGINE_COLUMNS.index("is_52w_low")] = np.nan
    return DailyFeatureRows(
        isin=isins,
        trade_date=np.array(days, dtype="datetime64[D]"),
        as_of_date=np.array(days, dtype="datetime64[D]"),
        primary_venue=["NSE"] * count,
        close=np.full(count, 991.2),
        figures=figures,
        venue_spread_bps=np.array([5.5] + [np.nan] * (count - 1)),
        is_day_complete=np.full(count, True),
        is_diverging=np.full(count, False),
    )


@pytest.fixture
def connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        for isin in (RELIANCE, HDFC_BANK):
            open_.execute(
                "insert into instrument_master (isin, name, country, instrument_type)"
                " values (%s, %s, 'IN', 'equity')",
                (isin, isin),
            )
        open_.commit()
        yield open_


def stored(connection: psycopg.Connection) -> list[tuple[object, ...]]:
    return connection.execute(
        "select isin, trade_date, rsi_14 from mart_daily_features order by isin, trade_date"
    ).fetchall()


def test_a_blank_figure_is_stored_as_null(connection: psycopg.Connection) -> None:
    replace_daily_features(connection, [feature_rows([HDFC_BANK], ["2025-12-31"])])

    row = connection.execute(
        "select close, return_1y, rsi_14, is_52w_high, is_52w_low, venue_spread_bps"
        " from mart_daily_features"
    ).fetchone()

    assert row == (Decimal("991.2000"), None, 50.0, True, None, 5.5)


def test_a_replacement_keeps_only_the_rows_its_batches_hold(
    connection: psycopg.Connection,
) -> None:
    replace_daily_features(
        connection, [feature_rows([HDFC_BANK, HDFC_BANK], ["2025-12-26", "2025-12-30"])]
    )
    assert len(stored(connection)) == 2

    written = replace_daily_features(
        connection, [feature_rows([RELIANCE], ["2025-12-31"], rsi=61.0)]
    )

    assert written == 1
    assert stored(connection) == [(RELIANCE, date(2025, 12, 31), 61.0)]


def test_every_batch_is_written_in_one_replacement(connection: psycopg.Connection) -> None:
    batches = [
        feature_rows([HDFC_BANK], ["2025-12-31"]),
        feature_rows([RELIANCE, RELIANCE], ["2025-12-29", "2025-12-31"]),
    ]

    written = replace_daily_features(connection, batches)

    assert written == 3
    assert len(stored(connection)) == 3


def test_a_refused_batch_leaves_the_stored_rows(connection: psycopg.Connection) -> None:
    replace_daily_features(connection, [feature_rows([HDFC_BANK], ["2025-12-30"])])
    rows = feature_rows([RELIANCE, RELIANCE], ["2025-12-30", "2025-12-31"])
    batches = [
        feature_rows([RELIANCE], ["2025-12-29"]),
        replace(rows, close=rows.close[:1]),
    ]

    with pytest.raises(FeatureWriteRefused):
        replace_daily_features(connection, batches)

    assert stored(connection) == [(HDFC_BANK, date(2025, 12, 30), 50.0)]


def test_replacements_inside_an_open_transaction_each_apply(
    connection: psycopg.Connection,
) -> None:
    assert stored(connection) == []

    replace_daily_features(connection, [feature_rows([HDFC_BANK], ["2025-12-31"])])
    replace_daily_features(connection, [feature_rows([RELIANCE], ["2025-12-31"], rsi=61.0)])

    assert stored(connection) == [(RELIANCE, date(2025, 12, 31), 61.0)]
