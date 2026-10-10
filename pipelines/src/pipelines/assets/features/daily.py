"""The daily features of every instrument, computed once the models they read are built.

Each run computes every instrument's whole history at both venues and replaces the stored rows, so
a corporate action, a change of ISIN or a corrected bar reaches every day it affects. The series is
read before the replacement begins, so readers of the table wait only while the rows are written.
"""

import logging

from dagster import AssetKey, MaterializeResult, asset

from pipelines.daily_features import replace_daily_features
from pipelines.feature_derivation import derive_daily_features
from pipelines.feature_inputs import read_action_dates, read_continuous_series, read_verdicts
from pipelines.resources import Database

logger = logging.getLogger(__name__)

MODELS = [
    AssetKey("int_continuous_prices"),
    AssetKey("int_capital_action_factors"),
    AssetKey("stg_trading_day"),
]


@asset(
    deps=MODELS,
    group_name="features",
    description="One row per instrument and day it traded at its primary venue: mart_daily_features.",
)
def daily_features(database: Database) -> MaterializeResult[None]:
    with database.connect() as connection:
        series = read_continuous_series(connection)
        actions = read_action_dates(connection)
        verdicts = read_verdicts(connection)
        written = replace_daily_features(
            connection, derive_daily_features(series, actions, verdicts)
        )
    logger.info("daily features replaced", extra={"rows": written})
    return MaterializeResult(metadata={"rows": written})
