"""The daily features of every instrument, computed once the models they read are built.

Each run computes every instrument's whole history at both venues, so a corporate action, a change
of ISIN or a corrected bar reaches every day it affects. The computation is written into the table
readers do not see and then published, so readers never wait for the write.
"""

import logging

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.daily_features import write_daily_features
from pipelines.feature_derivation import derive_daily_features
from pipelines.feature_inputs import read_action_dates, read_continuous_series, read_verdicts
from pipelines.feature_publication import publish, unpublished_table
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
def daily_features(context: AssetExecutionContext, database: Database) -> MaterializeResult[None]:
    with database.connect() as connection:
        series = read_continuous_series(connection)
        actions = read_action_dates(connection)
        verdicts = read_verdicts(connection)
        table = unpublished_table(connection)
        written = write_daily_features(
            connection, derive_daily_features(series, actions, verdicts), table
        )
        release = publish(connection, table, context.run_id)
    logger.info("daily features written", extra={"rows": written, "table": table})
    return MaterializeResult(
        metadata={
            "rows": written,
            "table": table,
            "trade_date": str(release.trade_date),
            "release_id": release.release_id,
        }
    )
