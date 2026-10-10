"""The daily feature inputs, read from the models built over the committed dataset."""

from datetime import date

import numpy as np
import psycopg
import pytest

from pipelines.feature_inputs import (
    SERIES_FIELDS,
    SERIES_ROW,
    ContinuousSeries,
    SeriesUnreadable,
    read_action_dates,
    read_continuous_series,
    read_verdicts,
    series_columns,
)

HDFC_BANK = b"INE040A01034"
NEW_YEARS_EVE = np.datetime64("2025-12-31", "D").astype(np.int64)


@pytest.fixture(scope="module")
def series(seeded_models: psycopg.Connection) -> ContinuousSeries:
    return read_continuous_series(seeded_models)


def counted(connection: psycopg.Connection, query: str) -> int:
    row = connection.execute(query).fetchone()
    assert row is not None
    return int(row[0])


def test_the_series_holds_every_bar_by_instrument_venue_and_day(
    seeded_models: psycopg.Connection, series: ContinuousSeries
) -> None:
    order = np.lexsort((series.day, series.is_nse, series.isin))

    assert len(series.day) == counted(seeded_models, "select count(*) from int_continuous_prices")
    assert np.array_equal(order, np.arange(len(order)))


def test_a_bar_reads_as_the_model_holds_it(series: ContinuousSeries) -> None:
    bar = np.flatnonzero((series.isin == HDFC_BANK) & series.is_nse & (series.day == NEW_YEARS_EVE))

    assert len(bar) == 1
    assert series.close_as_traded[bar[0]] == 991.2
    assert series.close[bar[0]] == 991.2
    assert series.adjustment_factor[bar[0]] == 1.0
    assert series.as_of_day[bar[0]] == NEW_YEARS_EVE
    assert series.source_isin[bar[0]] == HDFC_BANK


def test_a_missing_value_reads_as_nan(
    seeded_models: psycopg.Connection, series: ContinuousSeries
) -> None:
    without_delivery = counted(
        seeded_models, "select count(*) from int_continuous_prices where delivery_quantity is null"
    )

    assert np.count_nonzero(np.isnan(series.delivery)) == without_delivery > 0


def test_actions_and_verdicts_read_in_key_order(seeded_models: psycopg.Connection) -> None:
    actions = read_action_dates(seeded_models)
    verdicts = read_verdicts(seeded_models)

    assert len(actions.isin) == counted(
        seeded_models,
        "select count(*) from int_capital_action_factors where applied_factor is not null",
    )
    assert np.array_equal(np.lexsort((actions.ex_day, actions.isin)), np.arange(len(actions.isin)))
    assert len(verdicts.day) == counted(seeded_models, "select count(*) from stg_trading_day")
    assert np.array_equal(np.lexsort((verdicts.day, verdicts.is_nse)), np.arange(len(verdicts.day)))
    assert date(2025, 12, 31) in verdicts.day.astype("datetime64[D]").tolist()


def test_a_field_of_another_width_is_refused() -> None:
    rows = np.zeros(2, dtype=SERIES_ROW)
    rows["field_count"] = len(SERIES_FIELDS)
    for name in SERIES_FIELDS:
        rows[f"{name}_length"] = SERIES_ROW[name].itemsize
    series_columns(rows)
    rows["close_length"][1] = -1

    with pytest.raises(SeriesUnreadable):
        series_columns(rows)
