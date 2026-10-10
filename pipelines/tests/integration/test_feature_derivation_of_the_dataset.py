"""The daily feature rows of the committed dataset, against the models they are drawn from."""

import psycopg
import pytest

from pipelines.daily_features import DailyFeatureRows
from pipelines.feature_derivation import derive_daily_features
from pipelines.feature_inputs import read_action_dates, read_continuous_series, read_verdicts


@pytest.fixture(scope="module")
def rows(seeded_models: psycopg.Connection) -> list[DailyFeatureRows]:
    return list(
        derive_daily_features(
            read_continuous_series(seeded_models),
            read_action_dates(seeded_models),
            read_verdicts(seeded_models),
        )
    )


def test_each_day_has_one_row_per_instrument(rows: list[DailyFeatureRows]) -> None:
    keys = {
        (isin, day)
        for batch in rows
        for isin, day in zip(batch.isin, batch.trade_date.tolist(), strict=True)
    }

    assert len(keys) == sum(len(batch.isin) for batch in rows)


def test_no_row_diverges_where_every_day_is_complete(rows: list[DailyFeatureRows]) -> None:
    assert all(batch.is_day_complete.all() for batch in rows)
    assert not any(batch.is_diverging.any() for batch in rows)
