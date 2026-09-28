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
    AssetKey,
    BackfillPolicy,
    MaterializeResult,
    asset,
)

from pipelines.assets.ingestion.calendar import INGESTION_DAYS, calendar_days
from pipelines.facts import persist_bars, record_ingestion
from pipelines.identity import (
    derive_instruments,
    hold_instrument_writes,
    isins_by_scrip_code,
    name_instruments,
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
    # Each instrument the run reads, with the latest day it was read on and the name published that
    # day. Names are written once the run's bars are stored, so the order of reading decides none.
    read_names: dict[str, tuple[date, str]] = {}

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

            hold_instrument_writes(connection)
            # A scrip code day resolves every code to an instrument already stored and read on the
            # days around it, so it neither introduces nor names one.
            if version != SCRIP:
                names = names_by_isin(rows, venue)
                introduced = [
                    item for item in derive_instruments(bars, names) if item.isin not in read_names
                ]
                # Every fact references the instrument master, so an instrument a day introduces
                # is written before its bars, under that day's name. Listings and the primary venue
                # read the whole history and are derived downstream rather than one day at a time.
                persist_identity(connection, introduced, (), ())
                for bar in bars:
                    held = read_names.get(bar.isin)
                    if held is None or day > held[0]:
                        read_names[bar.isin] = (day, names.get(bar.isin, bar.isin))
            written += persist_bars(connection, bars)
            record_ingestion(
                connection, definition.source_id, partition, version, "succeeded", len(bars)
            )
            # Each day stands on its own, so a run interrupted part way keeps what it read.
            connection.commit()

            published += 1
            bars_read += len(bars)
            secondary_lines += len(lines) - len(bars)

        hold_instrument_writes(connection)
        renamed = name_instruments(connection, venue, read_names)
        connection.commit()

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
            "renamed": renamed,
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
            "instruments": len(read_names),
            "renamed": renamed,
        }
    )


@asset(
    partitions_def=INGESTION_DAYS,
    backfill_policy=BackfillPolicy.single_run(),
    deps=[AssetKey("source_registry")],
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
    deps=[AssetKey("source_registry")],
    group_name=GROUP,
    description="NSE equity bars for each trading day in the run.",
)
def nse_bhavcopy(
    context: AssetExecutionContext, database: Database, bhavcopies: Bhavcopies
) -> MaterializeResult[None]:
    return ingest(context, "NSE", database, bhavcopies)
