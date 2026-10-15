"""Venue comparison over the committed dataset, against the venue spread model."""

import numpy as np
import psycopg
import pytest

from pipelines.feature_inputs import read_continuous_series
from pipelines.venue_comparison import day_keys, venue_spread

# The model rounds the spread in decimals; the comparison rounds the same quotient in floats.
SPREAD_TOLERANCE_BPS = 1e-4


def test_every_bar_carries_the_spread_of_the_model(seeded_models: psycopg.Connection) -> None:
    series = read_continuous_series(seeded_models)
    instrument = np.cumsum(np.concatenate(([0], series.isin[1:] != series.isin[:-1])))
    spread, diverging = venue_spread(
        day_keys(instrument.astype(np.int64), series.day),
        series.is_nse,
        series.source_isin,
        series.close_as_traded,
        series.turnover,
    )
    modelled = {
        (isin.encode(), np.datetime64(day, "D").astype(np.int64)): value
        for isin, day, value in seeded_models.execute(
            "select isin, trade_date, venue_spread_bps::float8 from int_venue_spread"
        ).fetchall()
    }

    for source, day, value in zip(series.source_isin, series.day, spread, strict=True):
        if (source, day) in modelled:
            assert value == pytest.approx(modelled[source, day], abs=SPREAD_TOLERANCE_BPS)
        else:
            assert np.isnan(value)
    assert np.count_nonzero(~np.isnan(spread)) == 2 * len(modelled)
    assert not diverging.any()
