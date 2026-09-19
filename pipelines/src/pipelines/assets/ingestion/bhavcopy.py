"""One trading day of one venue's published prices, stored as it was published.

A partition is a weekday, since neither venue publishes at a weekend. A weekday the venue did not
publish is a holiday: the attempt is recorded and the day stores no bars, rather than failing.
"""

from datetime import date

from dagster import AssetExecutionContext, MaterializeResult, TimeWindowPartitionsDefinition, asset

from pipelines.facts import persist_bars, record_ingestion
from pipelines.identity import derive_instruments, persist_identity, require_resolvable
from pipelines.resources import Bhavcopies, Database
from pipelines.sources.bhavcopy import names_by_isin
from pipelines.sources.errors import NotPublished, SourceError

GROUP = "ingestion"

# Neither venue publishes at a weekend, so a Saturday partition would report a holiday every week.
WEEKDAYS = "0 0 * * 1-5"


def trading_days(venue: str) -> TimeWindowPartitionsDefinition:
    """Weekday partitions from the first day the registry has a parser for."""
    covered = Bhavcopies().definition(venue).schema_version
    first = min(version.effective_from for version in covered)
    return TimeWindowPartitionsDefinition(
        cron_schedule=WEEKDAYS, start=f"{first:%Y-%m-%d}", fmt="%Y-%m-%d"
    )


def ingest(
    context: AssetExecutionContext, venue: str, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    day = date.fromisoformat(context.partition_key)
    definition = bhavcopies.definition(venue)
    adapter = bhavcopies.adapter(venue)
    version = definition.version_for(day)

    with database.connect() as connection:
        try:
            rows = adapter.parse(adapter.fetch(day, version), version, day)
        except NotPublished as absence:
            record_ingestion(
                connection,
                definition.source_id,
                day.isoformat(),
                version,
                "not_published",
                detail=str(absence),
            )
            connection.commit()
            return MaterializeResult(
                metadata={"venue": venue, "bars": 0, "outcome": "not_published"}
            )
        except SourceError as failure:
            record_ingestion(
                connection,
                definition.source_id,
                day.isoformat(),
                version,
                "failed",
                detail=str(failure),
            )
            connection.commit()
            raise

        bars = require_resolvable(adapter.normalize(rows))
        names = names_by_isin(rows, venue)

        # Every fact references the instrument master, so the identities a day introduces are
        # written first. Listings and the primary venue read the whole history and are derived
        # downstream rather than one day at a time.
        persist_identity(connection, derive_instruments(bars, names), (), ())
        written = persist_bars(connection, bars)
        record_ingestion(
            connection, definition.source_id, day.isoformat(), version, "succeeded", len(bars)
        )
        connection.commit()

    context.log.info(
        "bhavcopy ingested",
        extra={
            "venue": venue,
            "trade_date": day.isoformat(),
            "bars": len(bars),
            "written": written,
        },
    )
    return MaterializeResult(
        metadata={
            "venue": venue,
            "bars": len(bars),
            "written": written,
            "instruments": len({bar.isin for bar in bars}),
            "schema_version": version,
            "outcome": "succeeded",
        }
    )


@asset(
    partitions_def=trading_days("BSE"),
    group_name=GROUP,
    description="BSE equity bars for one trading day.",
)
def bse_bhavcopy(
    context: AssetExecutionContext, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    return ingest(context, "BSE", database, bhavcopies)


@asset(
    partitions_def=trading_days("NSE"),
    group_name=GROUP,
    description="NSE equity bars for one trading day.",
)
def nse_bhavcopy(
    context: AssetExecutionContext, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    return ingest(context, "NSE", database, bhavcopies)
