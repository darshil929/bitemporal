"""The daily features of every instrument, computed once the models they read are built.

Each run computes every instrument's whole history at both venues, so a corporate action, a change
of ISIN or a corrected bar reaches every day it affects. The computation is written into the table
readers do not see, where the checks read it before it is published.
"""

import logging

from dagster import AssetKey, MaterializeResult, asset

from pipelines.daily_features import write_daily_features
from pipelines.feature_derivation import derive_daily_features
from pipelines.feature_inputs import read_action_dates, read_continuous_series, read_verdicts
from pipelines.feature_publication import unpublished_table
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
    description="One row per instrument and day it traded at its primary venue, not yet published.",
)
def daily_features(database: Database) -> MaterializeResult[None]:
    with database.connect() as connection:
        series = read_continuous_series(connection)
        actions = read_action_dates(connection)
        verdicts = read_verdicts(connection)
        table = unpublished_table(connection)
        written = write_daily_features(
            connection, derive_daily_features(series, actions, verdicts), table
        )
    logger.info("daily features written", extra={"rows": written, "table": table})
    return MaterializeResult(metadata={"rows": written, "table": table})
