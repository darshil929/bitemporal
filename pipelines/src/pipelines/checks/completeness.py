"""What validation has to have decided before the models downstream may read a day."""

from dagster import AssetCheckExecutionContext, AssetCheckResult, asset_check

from pipelines.assets.ingestion.completeness import trading_day_completeness
from pipelines.resources import Database

# A day nobody judged is neither complete nor incomplete, and a model reading it cannot tell.
UNJUDGED_DAYS = """
select count(*) from (
    select distinct p.venue, p.trade_date
    from price_daily p
    where not exists (
        select 1 from trading_day d where d.venue = p.venue and d.trade_date = p.trade_date
    )
) as unjudged
"""


@asset_check(
    asset=trading_day_completeness,
    blocking=True,
    description="Every stored day carries a verdict.",
)
def every_stored_day_has_a_verdict(
    context: AssetCheckExecutionContext, database: Database
) -> AssetCheckResult:
    with database.connect() as connection:
        row = connection.execute(UNJUDGED_DAYS).fetchone()

    unjudged = int(row[0]) if row else 0
    return AssetCheckResult(
        passed=unjudged == 0,
        metadata={"venue_days_without_a_verdict": unjudged},
        description="A day with bars and no verdict cannot be told from one that failed.",
    )
