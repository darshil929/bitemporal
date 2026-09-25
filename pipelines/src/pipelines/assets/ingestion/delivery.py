"""The shares each venue reports as settled rather than closed out, a trading day at a time.

Neither venue's delivery file names an instrument by ISIN. BSE names it by scrip code and NSE by
ticker, and both change ISIN when a face value changes, so a row resolves through the listing in
force on its own trade date rather than through whichever ISIN the identifier carries today.

NSE answers some days with the file of another day, so a file is held to the day it was asked
for. On a day the venue traded, a file that does not answer is followed by the other file NSE
publishes the same figures in.
"""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

import psycopg
from dagster import (
    AssetExecutionContext,
    AssetKey,
    BackfillPolicy,
    MaterializeResult,
    TimeWindowPartitionsDefinition,
    asset,
)

from pipelines.assets.ingestion.bhavcopy import EVERY_DAY, calendar_days
from pipelines.facts import persist_delivery, record_ingestion
from pipelines.resources import Bhavcopies, Database, Deliveries
from pipelines.sources.delivery import DeliveryRow, held_to
from pipelines.sources.errors import NotPublished, SourceError, WrongDay

GROUP = "ingestion"

# The identifier each venue's delivery file carries, from the listing in force on the day: the scrip
# code at BSE, and the ticker at NSE, which carries no scrip code.
IN_FORCE = """
select coalesce(scrip_code, local_symbol), isin
from listing
where exchange = %s
  and listing_date <= %s
  and (delisting_date is null or %s <= delisting_date)
"""


def delivery_days(venue: str) -> TimeWindowPartitionsDefinition:
    """Days from the later of the day delivery is served and the day prices begin.

    A delivery figure resolves through a listing, and a listing exists only where prices do.
    """
    served = Deliveries().definition(venue).schema_version
    priced = Bhavcopies().definition(venue).schema_version
    first = max(
        min(version.effective_from for version in served),
        min(version.effective_from for version in priced),
    )
    return TimeWindowPartitionsDefinition(
        cron_schedule=EVERY_DAY, start=f"{first:%Y-%m-%d}", fmt="%Y-%m-%d"
    )


# The price log's latest outcome for a day. A day with no prices published held no session.
LAST_PRICE_OUTCOME = """
select outcome
from ingestion_log
where source_id = %s and partition_key = %s
order by fetched_at desc
limit 1
"""


class DayReader(Protocol):
    def fetch(self, partition: date, schema_version: str) -> bytes: ...

    def parse(self, payload: bytes, schema_version: str) -> Sequence[DeliveryRow]: ...

    def fallback_for(self, schema_version: str) -> str | None: ...


def read_day(adapter: DayReader, day: date, version: str, venue: str) -> Sequence[DeliveryRow]:
    return held_to(adapter.parse(adapter.fetch(day, version), version), day, venue)


def outcome_for(failures: Sequence[SourceError], session: bool) -> str:
    """A day no file answered for is unpublished, unless a venue that traded served a wrong one."""
    if all(isinstance(failure, NotPublished) for failure in failures):
        return "not_published"
    if not session and all(isinstance(failure, NotPublished | WrongDay) for failure in failures):
        return "not_published"
    return "failed"


def held_no_session(connection: psycopg.Connection, price_source: str, day: date) -> bool:
    found = connection.execute(LAST_PRICE_OUTCOME, (price_source, day.isoformat())).fetchone()
    return found is not None and found[0] == "not_published"


def resolver(connection: psycopg.Connection, venue: str, day: date) -> dict[str, str]:
    return {key: isin for key, isin in connection.execute(IN_FORCE, (venue, day, day))}


def ingest_delivery(
    context: AssetExecutionContext, venue: str, database: Database, deliveries: Deliveries
) -> MaterializeResult[None]:
    window = context.partition_key_range
    definition = deliveries.definition(venue)
    adapter = deliveries.adapter(venue)
    price_source = Bhavcopies().definition(venue).source_id

    published = unpublished = failed = written = 0

    with database.connect() as connection:
        for day in calendar_days(date.fromisoformat(window.start), date.fromisoformat(window.end)):
            partition = day.isoformat()
            version = definition.version_for(day)

            failures: list[SourceError] = []
            rows: Sequence[DeliveryRow] = ()
            try:
                rows = read_day(adapter, day, version, venue)
            except SourceError as first:
                failures.append(first)

            session = True
            if failures:
                session = not held_no_session(connection, price_source, day)
                alternative = adapter.fallback_for(version) if session else None
                if alternative is not None:
                    try:
                        rows = read_day(adapter, day, alternative, venue)
                        version, failures = alternative, []
                    except SourceError as second:
                        failures.append(second)

            if failures:
                outcome = outcome_for(failures, session)
                detail = "; ".join(str(failure) for failure in failures)
                record_ingestion(
                    connection, definition.source_id, partition, version, outcome, detail=detail
                )
                connection.commit()
                if outcome == "not_published":
                    unpublished += 1
                    continue
                failed += 1
                context.log.warning(
                    "delivery could not be read",
                    extra={"venue": venue, "trade_date": partition, "detail": detail},
                )
                continue

            records = adapter.normalize(rows, resolver(connection, venue, day))
            written += persist_delivery(connection, records)
            record_ingestion(
                connection, definition.source_id, partition, version, "succeeded", len(records)
            )
            connection.commit()
            published += 1

    if failed and not published:
        raise SourceError(
            f"{venue} published no readable delivery between {window.start} and {window.end}"
        )

    context.log.info(
        "delivery ingested",
        extra={"venue": venue, "published": published, "failed": failed, "written": written},
    )
    return MaterializeResult(
        metadata={
            "venue": venue,
            "from": window.start,
            "to": window.end,
            "published": published,
            "unpublished": unpublished,
            "failed": failed,
            "written": written,
        }
    )


@asset(
    partitions_def=delivery_days("BSE"),
    backfill_policy=BackfillPolicy.single_run(),
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="BSE delivery quantities for each trading day in the run.",
)
def bse_delivery(
    context: AssetExecutionContext, database: Database, deliveries: Deliveries
) -> MaterializeResult[None]:
    return ingest_delivery(context, "BSE", database, deliveries)


@asset(
    partitions_def=delivery_days("NSE"),
    backfill_policy=BackfillPolicy.single_run(),
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="NSE delivery quantities for each trading day in the run.",
)
def nse_delivery(
    context: AssetExecutionContext, database: Database, deliveries: Deliveries
) -> MaterializeResult[None]:
    return ingest_delivery(context, "NSE", database, deliveries)
