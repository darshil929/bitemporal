"""Every watchlist alert judged on the sessions published since it was last judged.

The figures are read once this run has published its daily features, and each verdict is appended,
so a run writes a session's verdict at most once for each day its figure became known.
"""

import logging

from dagster import MaterializeResult, asset

from pipelines.assets.features.publication import daily_feature_publication
from pipelines.resources import Database
from pipelines.watchlist_alert_evaluation import evaluate_alerts

logger = logging.getLogger(__name__)


@asset(
    deps=[daily_feature_publication],
    group_name="watchlist",
    description="Each watchlist alert's verdict on every session its venue published.",
)
def watchlist_alert_evaluation(database: Database) -> MaterializeResult[None]:
    with database.connect() as connection:
        evaluated = evaluate_alerts(connection)
    counts = {
        "verdicts": evaluated.judged,
        "triggered": evaluated.triggered,
        "paused": evaluated.paused,
    }
    logger.info("watchlist alerts judged", extra=counts)
    return MaterializeResult(metadata=counts)
