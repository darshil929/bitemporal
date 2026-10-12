"""The daily features are written a computation at a time into the table readers do not see, and
published by pointing the view readers query at it."""

from collections.abc import Iterable, Iterator
from dataclasses import replace
from datetime import date
from decimal import Decimal

import numpy as np
import psycopg
import pytest
from alembic.config import Config

from fixtures.database import MIGRATION_SCHEMA
from pipelines.daily_features import (
    ENGINE_COLUMNS,
    DailyFeatureRows,
    FeatureWriteRefused,
    write_daily_features,
)
from pipelines.feature_publication import (
    PublicationRefused,
    publish,
    published_table,
    unpublished_table,
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


def replace_daily_features(
    connection: psycopg.Connection, batches: Iterable[DailyFeatureRows]
) -> int:
    table = unpublished_table(connection)
    written = write_daily_features(connection, batches, table)
    publish(connection, table, run_id=None)
    return written


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


def test_a_computation_is_written_where_readers_do_not_look(
    connection: psycopg.Connection,
) -> None:
    replace_daily_features(connection, [feature_rows([HDFC_BANK], ["2025-12-30"])])
    table = unpublished_table(connection)

    write_daily_features(connection, [feature_rows([RELIANCE], ["2025-12-31"])], table)

    assert stored(connection) == [(HDFC_BANK, date(2025, 12, 30), 50.0)]
    publish(connection, table, run_id="run-2")
    assert published_table(connection) == table
    assert stored(connection) == [(RELIANCE, date(2025, 12, 31), 50.0)]


def test_a_publish_records_the_newest_day_and_the_rows(connection: psycopg.Connection) -> None:
    table = unpublished_table(connection)
    write_daily_features(
        connection, [feature_rows([HDFC_BANK, RELIANCE], ["2025-12-30", "2025-12-31"])], table
    )

    release = publish(connection, table, run_id="run-1")

    recorded = connection.execute(
        "select table_name, trade_date, row_count, run_id from feature_release"
        " where release_id = %s",
        (release.release_id,),
    ).fetchone()
    assert recorded == (table, date(2025, 12, 31), 2, "run-1")


def test_the_previous_computation_stays_in_the_other_table(
    connection: psycopg.Connection,
) -> None:
    replace_daily_features(connection, [feature_rows([HDFC_BANK], ["2025-12-30"])])
    replace_daily_features(connection, [feature_rows([RELIANCE], ["2025-12-31"])])

    previous = connection.execute(
        f"select isin, trade_date from {unpublished_table(connection)}"
    ).fetchall()

    assert previous == [(HDFC_BANK, date(2025, 12, 30))]


def test_a_day_is_stored_together(connection: psycopg.Connection) -> None:
    table = unpublished_table(connection)
    batches = [
        feature_rows([HDFC_BANK, HDFC_BANK], ["2025-12-29", "2025-12-31"]),
        feature_rows([RELIANCE, RELIANCE], ["2025-12-29", "2025-12-31"]),
    ]

    write_daily_features(connection, batches, table)

    in_storage = connection.execute(
        f"select isin, trade_date from {table} order by ctid"
    ).fetchall()
    assert [day for _, day in in_storage] == sorted(day for _, day in in_storage)


def test_a_publish_gives_up_on_a_reader_holding_the_view(
    connection: psycopg.Connection, postgres_dsn: str
) -> None:
    table = unpublished_table(connection)
    connection.commit()
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as reader:
        reader.execute("select count(*) from mart_daily_features")

        with pytest.raises(PublicationRefused):
            publish(connection, table, run_id=None, attempts=2, lock_timeout="50ms")

    assert publish(connection, table, run_id=None).table_name == table
