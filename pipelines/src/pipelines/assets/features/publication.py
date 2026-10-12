"""The daily features a run computed, published once every check on them has passed.

The checks on the computation block this step, so a computation breaking a rule is never published
and readers keep the one published before. A run publishes only the computation it wrote itself:
the table readers do not see otherwise holds the computation published before the last.
"""

from dagster import AssetExecutionContext, MaterializeResult, asset

from pipelines.assets.features.daily import daily_features
from pipelines.feature_publication import PublicationRefused, publish, unpublished_table
from pipelines.resources import Database


@asset(
    deps=[daily_features],
    group_name="features",
    description="mart_daily_features pointed at the computation this run wrote and checked.",
)
def daily_feature_publication(
    context: AssetExecutionContext, database: Database
) -> MaterializeResult[None]:
    written = context.instance.get_latest_materialization_event(daily_features.key)
    materialization = written.asset_materialization if written else None
    if written is None or materialization is None or written.run_id != context.run.run_id:
        raise PublicationRefused("no daily features were computed in this run")

    with database.connect() as connection:
        table = unpublished_table(connection)
        if materialization.metadata["table"].value != table:
            raise PublicationRefused(f"this run's daily features are not in {table}")
        release = publish(connection, table, context.run.run_id)
    return MaterializeResult(
        metadata={
            "table": table,
            "trade_date": str(release.trade_date),
            "rows": release.row_count,
            "release_id": release.release_id,
        }
    )
