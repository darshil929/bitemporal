"""One venue's published prices, stored as they were published.

A partition is a calendar day, since both venues trade on the occasional weekend: a Diwali
Muhurat, a Budget day or a special session. A day the venue did not publish stores no bars, and
neither does a day it published badly; each attempt is recorded, and the run carries on with the
days it could read.

A run covers a range of days, reading them through one throttled client and one venue session.
"""

from collections.abc import Iterable, Sequence
from datetime import date

import psycopg
from dagster import (
    AssetExecutionContext,
    AssetKey,
    BackfillPolicy,
    MaterializeResult,
    asset,
)

from pipelines.assets.ingestion.calendar import (
    INGESTION_DAYS,
    RECHECKED_DAYS,
    calendar_days,
    recheck_day,
)
from pipelines.facts import persist_bars, record_ingestion
from pipelines.history import latest_days_held, read_bars
from pipelines.identity import (
    derive_instruments,
    hold_instrument_writes,
    isins_by_scrip_code,
    name_instruments,
    persist_identity,
    resolvable,
)
from pipelines.models.market import PriceBar
from pipelines.resources import Bhavcopies, Database
from pipelines.sources.bhavcopy import names_by_isin, ordinary_lines
from pipelines.sources.bse.bhavcopy import SCRIP, UDIFF
from pipelines.sources.errors import NotPublished, SourceError
from pipelines.sources.legacy import named_by_isin
from pipelines.sources.registry import SourceDefinition

GROUP = "ingestion"


def reading_order(days: Iterable[date], definition: SourceDefinition) -> list[date]:
    """The days of a run in the order they are read, BSE's scrip code days after every other.

    A scrip code day resolves each code through the bars stored on the days around it.
    """
    return sorted(days, key=lambda day: definition.version_for(day) == SCRIP)


def corrected_bars(
    connection: psycopg.Connection, venue: str, day: date, bars: Sequence[PriceBar], noticed: date
) -> list[PriceBar]:
    """The bars of a corrected file that differ from the version standing, dated the day noticed."""
    standing = {bar.isin: bar for bar in read_bars(connection, day) if bar.venue == venue}
    dated = [bar.model_copy(update={"as_of_date": noticed}) for bar in bars]
    return [
        bar
        for bar in dated
        if (held := standing.get(bar.isin)) is None
        or held.model_copy(update={"as_of_date": noticed}) != bar
    ]


def ingest(
    context: AssetExecutionContext,
    venue: str,
    database: Database,
    bhavcopies: Bhavcopies,
    recheck_on: date | None = None,
) -> MaterializeResult[None]:
    window = context.partition_key_range
    definition = bhavcopies.definition(venue)
    adapter = bhavcopies.adapter(venue)

    published = unpublished = failed = written = rechecked = corrected = recheck_failed = 0
    bars_read = secondary_lines = 0
    days = list(calendar_days(date.fromisoformat(window.start), date.fromisoformat(window.end)))
    # A day outside every format the registry holds for the venue is passed over without a request.
    covered = [day for day in days if definition.covers(day)]
    outside_coverage = len(days) - len(covered)
    # Each instrument the run reads, with the latest day it was read on and the name published that
    # day. Names are written once the run's bars are stored, so the order of reading decides none.
    read_names: dict[str, tuple[date, str]] = {}

    with database.connect() as connection:
        days_to_recheck = set()
        if recheck_on is not None and days:
            days_to_recheck = set(
                latest_days_held(connection, venue, days[0], days[-1], RECHECKED_DAYS)
            )
        for day in reading_order(covered, definition):
            partition = day.isoformat()
            version = definition.version_for(day)

            if day in days_to_recheck and version == UDIFF and recheck_on is not None:
                try:
                    adapter.recheck(day, recheck_on)
                    rechecked += 1
                except SourceError as failure:
                    recheck_failed += 1
                    context.log.warning(
                        "trading day could not be asked for again",
                        extra={"venue": venue, "trade_date": partition, "detail": str(failure)},
                    )

            try:
                rows = adapter.parse(adapter.fetch(day, version), version, day)
                # BSE's scrip code file names no ISIN. Its rows resolve through the bars the ISIN
                # files of the days around it stored.
                if version == SCRIP:
                    rows = named_by_isin(rows, isins_by_scrip_code(connection, day))
                lines = resolvable(adapter.normalize(rows))
                bars = ordinary_lines(lines)
                files = adapter.corrections(day) if version == UDIFF else []
                corrections = [
                    (noticed, adapter.parse(file, version, day)) for noticed, file in files
                ]
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
                # is written before its bars, under that day's name. Listings read the whole
                # history and are derived downstream rather than one day at a time.
                persist_identity(connection, introduced, ())
                for bar in bars:
                    held = read_names.get(bar.isin)
                    if held is None or day > held[0]:
                        read_names[bar.isin] = (day, names.get(bar.isin, bar.isin))
            written += persist_bars(connection, bars)
            record_ingestion(
                connection, definition.source_id, partition, version, "succeeded", len(bars)
            )
            # A corrected file is read after the one it corrects, and only what it changed is
            # stored, dated the day it was noticed.
            for noticed, read in corrections:
                changed = corrected_bars(
                    connection,
                    venue,
                    day,
                    ordinary_lines(resolvable(adapter.normalize(read))),
                    noticed,
                )
                persist_identity(
                    connection, derive_instruments(changed, names_by_isin(read, venue)), ()
                )
                corrected += persist_bars(connection, changed)
                record_ingestion(
                    connection,
                    definition.source_id,
                    f"{partition}.as-of-{noticed:%Y%m%d}",
                    version,
                    "succeeded",
                    len(changed),
                )
            # Each day stands on its own, so a run interrupted part way keeps what it read.
            connection.commit()

            published += 1
            bars_read += len(bars)
            secondary_lines += len(lines) - len(bars)

        hold_instrument_writes(connection)
        renamed = name_instruments(connection, venue, read_names)
        connection.commit()

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
            "rechecked": rechecked,
            "corrected": corrected,
            "recheck_failed": recheck_failed,
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
            "rechecked": rechecked,
            "corrected": corrected,
            "recheck_failed": recheck_failed,
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
    return ingest(context, "BSE", database, bhavcopies, recheck_day(context))


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
    return ingest(context, "NSE", database, bhavcopies, recheck_day(context))
