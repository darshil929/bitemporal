"""One venue's published prices, stored as they were published.

A partition is a calendar day, since both venues trade on the occasional weekend: a Diwali
Muhurat, a Budget day or a special session. A day the venue did not publish stores no bars: the
attempt is recorded rather than failing.

A run covers a range of days, reading them through one throttled client and one venue session.
"""

from collections.abc import Iterable
from datetime import date

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    asset,
)

from pipelines.assets.ingestion.calendar import INGESTION_DAYS, calendar_days
from pipelines.facts import persist_bars, record_ingestion
from pipelines.identity import (
    derive_instruments,
    isins_by_scrip_code,
    persist_identity,
    resolvable,
)
from pipelines.resources import Bhavcopies, Database
from pipelines.sources.bhavcopy import names_by_isin, ordinary_lines
from pipelines.sources.bse.bhavcopy import SCRIP
from pipelines.sources.errors import NotPublished, SourceError
from pipelines.sources.legacy import named_by_isin
from pipelines.sources.registry import SourceDefinition

GROUP = "ingestion"


def reading_order(days: Iterable[date], definition: SourceDefinition) -> list[date]:
    """The days of a run in the order they are read, BSE's scrip code days after every other.

    A scrip code day resolves each code through the bars stored on the days around it.
    """
    return sorted(days, key=lambda day: definition.version_for(day) == SCRIP)


def ingest(
    context: AssetExecutionContext, venue: str, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    window = context.partition_key_range
    definition = bhavcopies.definition(venue)
    adapter = bhavcopies.adapter(venue)

    published = unpublished = failed = written = 0
    bars_read = secondary_lines = 0
    days = list(calendar_days(date.fromisoformat(window.start), date.fromisoformat(window.end)))
    # A day outside every format the registry holds for the venue is passed over without a request.
    covered = [day for day in days if definition.covers(day)]
    outside_coverage = len(days) - len(covered)
    # The same instruments appear on every day of a run, under the same names. A name already
    # stored stands until the venue publishes a different one.
    named: dict[str, str] = {}

    with database.connect() as connection:
        for day in reading_order(covered, definition):
            partition = day.isoformat()
            version = definition.version_for(day)

            try:
                rows = adapter.parse(adapter.fetch(day, version), version, day)
                # BSE's scrip code file names no ISIN. Its rows resolve through the bars the ISIN
                # files of the days around it stored.
                if version == SCRIP:
                    rows = named_by_isin(rows, isins_by_scrip_code(connection, day))
                lines = resolvable(adapter.normalize(rows))
                bars = ordinary_lines(lines)
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
                # A day the venue published badly costs that day and no more of the run.
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

            # Every code on a scrip code day resolves to an instrument already stored, and the day is
            # read after the days around it, so it leaves the names they wrote in place.
            introduced = (
                () if version == SCRIP else derive_instruments(bars, names_by_isin(rows, venue))
            )
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
            secondary_lines += len(lines) - len(bars)

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
            "outside_coverage": outside_coverage,
            "bars": bars_read,
            "secondary_lines": secondary_lines,
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
            "outside_coverage": outside_coverage,
            "bars": bars_read,
            "secondary_lines": secondary_lines,
            "written": written,
            "instruments": len(named),
        }
    )


@asset(
    partitions_def=INGESTION_DAYS,
    backfill_policy=BackfillPolicy.single_run(),
    group_name=GROUP,
    description="BSE equity bars for each trading day in the run.",
)
def bse_bhavcopy(
    context: AssetExecutionContext, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    return ingest(context, "BSE", database, bhavcopies)


@asset(
    partitions_def=INGESTION_DAYS,
    backfill_policy=BackfillPolicy.single_run(),
    group_name=GROUP,
    description="NSE equity bars for each trading day in the run.",
)
def nse_bhavcopy(
    context: AssetExecutionContext, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    return ingest(context, "NSE", database, bhavcopies)
