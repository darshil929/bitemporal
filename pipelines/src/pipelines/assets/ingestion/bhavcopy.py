"""One venue's published prices, stored as they were published.

A partition is a weekday, since neither venue publishes at a weekend. A weekday the venue did not
publish is a holiday: the attempt is recorded and the day stores no bars, rather than failing.

A run covers a range of days rather than one, so a backfill reads the whole history through a
single throttled client and a single session instead of building both for every day.
"""

from collections.abc import Iterator
from datetime import date, timedelta

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    TimeWindowPartitionsDefinition,
    asset,
)

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


def weekdays(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def ingest(
    context: AssetExecutionContext, venue: str, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    window = context.partition_key_range
    definition = bhavcopies.definition(venue)
    adapter = bhavcopies.adapter(venue)

    published = unpublished = failed = written = 0
    bars_read = 0
    # The same few thousand instruments appear on every day of the run. Writing each one again
    # for every day is most of what a long run spends on identity, so a name already stored by
    # this run is left alone until the venue publishes a different one.
    named: dict[str, str] = {}

    with database.connect() as connection:
        for day in weekdays(date.fromisoformat(window.start), date.fromisoformat(window.end)):
            partition = day.isoformat()
            version = definition.version_for(day)

            try:
                rows = adapter.parse(adapter.fetch(day, version), version, day)
            except NotPublished as absence:
                record_ingestion(
                    connection,
                    definition.source_id,
                    partition,
                    version,
                    "not_published",
                    detail=str(absence),
                )
                unpublished += 1
                connection.commit()
                continue
            except SourceError as failure:
                # One day the venue published badly costs that day. A run covering years of
                # them would otherwise end on the first, discarding everything read before it.
                record_ingestion(
                    connection,
                    definition.source_id,
                    partition,
                    version,
                    "failed",
                    detail=str(failure),
                )
                failed += 1
                connection.commit()
                context.log.warning(
                    "trading day could not be read",
                    extra={"venue": venue, "trade_date": partition, "detail": str(failure)},
                )
                continue

            bars = require_resolvable(adapter.normalize(rows))
            names = names_by_isin(rows, venue)
            introduced = derive_instruments(bars, names)
            unwritten = [item for item in introduced if named.get(item.isin) != item.name]

            # Every fact references the instrument master, so the identities a day introduces are
            # written first. Listings and the primary venue read the whole history and are derived
            # downstream rather than one day at a time.
            persist_identity(connection, unwritten, (), ())
            named.update((item.isin, item.name) for item in unwritten)
            written += persist_bars(connection, bars)
            record_ingestion(
                connection, definition.source_id, partition, version, "succeeded", len(bars)
            )
            # Each day stands on its own, so a run interrupted part way keeps what it read.
            connection.commit()

            published += 1
            bars_read += len(bars)

    if failed and not published:
        raise SourceError(
            f"{venue} published no readable day between {window.start} and {window.end}"
        )

    context.log.info(
        "bhavcopy ingested",
        extra={
            "venue": venue,
            "from": window.start,
            "to": window.end,
            "published": published,
            "unpublished": unpublished,
            "failed": failed,
            "bars": bars_read,
        },
    )
    return MaterializeResult(
        metadata={
            "venue": venue,
            "from": window.start,
            "to": window.end,
            "published": published,
            "unpublished": unpublished,
            "failed": failed,
            "bars": bars_read,
            "written": written,
            "instruments": len(named),
        }
    )


@asset(
    partitions_def=trading_days("BSE"),
    backfill_policy=BackfillPolicy.single_run(),
    group_name=GROUP,
    description="BSE equity bars for each trading day in the run.",
)
def bse_bhavcopy(
    context: AssetExecutionContext, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    return ingest(context, "BSE", database, bhavcopies)


@asset(
    partitions_def=trading_days("NSE"),
    backfill_policy=BackfillPolicy.single_run(),
    group_name=GROUP,
    description="NSE equity bars for each trading day in the run.",
)
def nse_bhavcopy(
    context: AssetExecutionContext, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    return ingest(context, "NSE", database, bhavcopies)
