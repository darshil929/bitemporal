"""Every corporate action NSE has recorded, read to check BSE's rather than to adjust prices.

A row names an ISIN, which for an instrument that changed face value can be one it carried years
before. Each is recorded under the ISIN it has since become, following the successions identity
derived, so an action lines up with BSE's for the same instrument.
"""

from datetime import date, datetime

import psycopg
from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.assets.ingestion.corporate_actions import VENUE_TIME, collect_ranges
from pipelines.resources import Database, NseActions
from pipelines.sources.nse.corporate_actions import years

GROUP = "ingestion"

# Successions at NSE first, since the venue's own records name its ISINs, then at BSE.
SUCCESSIONS = """
select predecessor_isin, successor_isin
from instrument_succession
order by case exchange when 'NSE' then 0 else 1 end
"""


def isins_now(connection: psycopg.Connection) -> dict[str, str]:
    """Every ISIN held, mapped onto the one it trades under now, itself where it never changed."""
    successor: dict[str, str] = {}
    for predecessor, following in connection.execute(SUCCESSIONS):
        successor.setdefault(predecessor, following)

    mapping = {}
    for (isin,) in connection.execute("select isin from instrument_master"):
        now, seen = isin, {isin}
        while now in successor and successor[now] not in seen:
            now = successor[now]
            seen.add(now)
        mapping[isin] = now
    return mapping


def ingest_nse_actions(
    context: AssetExecutionContext,
    database: Database,
    actions: NseActions,
    ranges: list[tuple[date, date]],
    collected_on: date,
) -> MaterializeResult[None]:
    with database.connect() as connection:
        mapping = isins_now(connection)
        return collect_ranges(
            context,
            connection,
            actions.definition(),
            actions.adapter(),
            ranges,
            collected_on,
            mapping,
            mapping,
        )


@asset(
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="Corporate actions NSE reports for every listed security, read to check BSE's.",
)
def nse_corporate_actions(
    context: AssetExecutionContext, database: Database, nse_actions: NseActions
) -> MaterializeResult[None]:
    collected_on = datetime.now(VENUE_TIME).date()
    return ingest_nse_actions(context, database, nse_actions, years(collected_on), collected_on)
