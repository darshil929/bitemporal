"""Whether each stored day may be read downstream, decided once both venues have published it.

Validation compares the two venues, so it runs over stored days rather than inside the ingestion
of one. A day carrying no verdict has not been checked, and a day corrected after its verdict is
checked again, the correction carrying a later as-of date than the verdict standing. A day whose
bars no longer number what its verdict was drawn from, because bars describing it were read
into the history afterwards, is judged again and recorded on the day it was judged.
"""

from collections.abc import Sequence
from datetime import date, datetime

import psycopg
from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.history import (
    days_awaiting_a_verdict,
    days_whose_bars_changed,
    read_bars,
    typical_bars,
)
from pipelines.resources import Database
from pipelines.validation import DayVerdict, persist_verdicts, validate_day

GROUP = "ingestion"

BHAVCOPIES = [AssetKey("bse_bhavcopy"), AssetKey("nse_bhavcopy")]


def judge(
    connection: psycopg.Connection,
    days: Sequence[date],
    usual: dict[str, int],
    judged_on: date | None,
) -> list[DayVerdict]:
    verdicts = []
    for day in days:
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
                    judged_on=judged_on,
                )
            )
    return verdicts


@asset(
    deps=BHAVCOPIES,
    group_name=GROUP,
    description="The verdict on each stored trading day, per venue.",
)
def trading_day_completeness(
    context: AssetExecutionContext, database: Database
) -> MaterializeResult[None]:
    judged_on = datetime.now(VENUE_TIME).date()
    with database.connect() as connection:
        usual = typical_bars(connection)
        awaiting = days_awaiting_a_verdict(connection)
        awaited = set(awaiting)
        changed = [day for day in days_whose_bars_changed(connection) if day not in awaited]

        verdicts = [
            *judge(connection, awaiting, usual, None),
            *judge(connection, changed, usual, judged_on),
        ]
        persist_verdicts(connection, verdicts)
        connection.commit()

    incomplete = sum(1 for verdict in verdicts if not verdict.is_complete)
    context.log.info("days validated", extra={"days": len(verdicts), "incomplete": incomplete})
    return MaterializeResult(
        metadata={
            "venue_days_validated": len(verdicts),
            "days_judged_again": len(changed),
            "incomplete": incomplete,
            "divergent_instruments": sum(item.divergent_instruments for item in verdicts),
        }
    )
