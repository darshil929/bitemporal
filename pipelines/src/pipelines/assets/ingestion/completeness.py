"""Whether each stored day may be read downstream, decided once both venues have published it.

Validation compares the two venues, so it runs over stored days rather than inside the ingestion
of one. A day carrying no verdict has not been checked, and a day corrected after its verdict is
checked again, the correction carrying a later as-of date than the verdict standing.
"""

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.history import days_awaiting_a_verdict, read_bars, typical_bars
from pipelines.resources import Database
from pipelines.validation import persist_verdicts, validate_day

GROUP = "ingestion"

BHAVCOPIES = [AssetKey("bse_bhavcopy"), AssetKey("nse_bhavcopy")]


@asset(
    deps=BHAVCOPIES,
    group_name=GROUP,
    description="The verdict on each stored trading day, per venue.",
)
def trading_day_completeness(
    context: AssetExecutionContext, database: Database
) -> MaterializeResult[None]:
    with database.connect() as connection:
        usual = typical_bars(connection)
        verdicts = []

        for day in days_awaiting_a_verdict(connection):
            bars = read_bars(connection, day)
            for venue in sorted({bar.venue for bar in bars}):
                published = [bar for bar in bars if bar.venue == venue]
                verdicts.append(
                    validate_day(
                        venue,
                        day,
                        published,
                        cross_venue_bars=[bar for bar in bars if bar.venue != venue],
                        typical_bars=usual.get(venue),
                    )
                )

        persist_verdicts(connection, verdicts)
        connection.commit()

    incomplete = sum(1 for verdict in verdicts if not verdict.is_complete)
    context.log.info("days validated", extra={"days": len(verdicts), "incomplete": incomplete})
    return MaterializeResult(
        metadata={
            "venue_days_validated": len(verdicts),
            "incomplete": incomplete,
            "divergent_instruments": sum(item.divergent_instruments for item in verdicts),
        }
    )
