"""Whether each stored day may be read downstream, decided once both venues have published it.

Validation compares the two venues, so it runs over stored days rather than inside the ingestion
of one. A day carrying no verdict has not been checked, and a day corrected after its verdict is
checked again, the correction carrying a later as-of date than the verdict standing. A day whose
bars no longer number what its verdict was drawn from, because bars describing it were read
into the history afterwards, is judged again. So is a day on which one venue was judged before
another venue's bars arrived. A venue's first verdict on a day is dated the day, and a verdict that
restates one is recorded on the day it was judged.
"""

from collections.abc import Sequence
from datetime import date, datetime

import psycopg
from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.history import (
    days_awaiting_a_verdict,
    days_whose_bars_changed,
    days_whose_venues_disagree,
    read_bars,
    typical_bars,
    venue_days_judged,
)
from pipelines.resources import Database
from pipelines.validation import DayVerdict, persist_verdicts, validate_day

GROUP = "ingestion"

BHAVCOPIES = [AssetKey("bse_bhavcopy"), AssetKey("nse_bhavcopy")]


def judge(
    connection: psycopg.Connection,
    days: Sequence[date],
    usual: dict[str, int],
    judged_on: date,
) -> list[DayVerdict]:
    """Each venue's verdict on each day, dated `judged_on` where the venue already carries one."""
    judged = venue_days_judged(connection, days)
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
                    judged_on=judged_on if (venue, day) in judged else None,
                )
            )
    return verdicts


def record_verdicts(connection: psycopg.Connection, judged_on: date) -> dict[str, int]:
    """Judge every stored day that needs a verdict, record them, and count what was done."""
    usual = typical_bars(connection)
    awaiting = days_awaiting_a_verdict(connection)
    awaited = set(awaiting)
    changed = [day for day in days_whose_bars_changed(connection) if day not in awaited]
    verdicts = judge(connection, [*awaiting, *changed], usual, judged_on)
    recorded = persist_verdicts(connection, verdicts)

    # A venue and day hold one verdict per as-of date, so a restatement drawn on the trade date
    # itself is refused, and the day stays in disagreement until a run on a later date.
    disagreeing = days_whose_venues_disagree(connection)
    restated = judge(connection, disagreeing, usual, judged_on)
    recorded += persist_verdicts(connection, restated)

    drawn = [*verdicts, *restated]
    return {
        "venue_days_validated": len(drawn),
        "venue_days_recorded": recorded,
        "days_judged_again": len(changed),
        "days_venues_disagreed": len(disagreeing),
        "incomplete": sum(1 for verdict in drawn if not verdict.is_complete),
        "divergent_instruments": sum(verdict.divergent_instruments for verdict in drawn),
    }


@asset(
    deps=BHAVCOPIES,
    group_name=GROUP,
    description="The verdict on each stored trading day, per venue.",
)
def trading_day_completeness(
    context: AssetExecutionContext, database: Database
) -> MaterializeResult[None]:
    with database.connect() as connection:
        summary = record_verdicts(connection, datetime.now(VENUE_TIME).date())
        connection.commit()

    context.log.info("days validated", extra=summary)
    return MaterializeResult(metadata=summary)
