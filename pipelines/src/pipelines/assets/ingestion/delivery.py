"""The shares each venue reports as settled rather than closed out, a trading day at a time.

Neither venue's delivery file names an instrument by ISIN. BSE names it by scrip code and NSE by
ticker, and both change ISIN when a face value changes, so a row resolves through the listing in
force on its own trade date rather than through whichever ISIN the identifier carries today.

NSE answers some days with the file of another day, so a file is held to the day it was asked
for. On a day the venue traded, a file that does not answer is followed by the other file NSE
publishes the same figures in. A day no file answers for is recorded, and the run carries on.
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
    asset,
)

from pipelines.assets.ingestion.calendar import (
    INGESTION_DAYS,
    RECHECKED_DAYS,
    calendar_days,
    recheck_day,
)
from pipelines.facts import persist_delivery, record_ingestion
from pipelines.history import latest_days_held
from pipelines.models.market import DeliveryRecord
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

    def recheck(self, partition: date, noticed_on: date) -> bytes | None: ...

    def corrections(self, partition: date) -> list[tuple[date, bytes]]: ...

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


# A delivery figure is part of a bar's day. A venue's delivery file can name an instrument its
# price file carries no equity line for that day: a fund BSE moved into its debt group, a line
# BSE ran into another, a day whose price file the venue did not publish.
PRICED = """
select isin
from price_daily
where venue = %s and trade_date = %s
"""


def priced(connection: psycopg.Connection, venue: str, day: date) -> set[str]:
    return {isin for (isin,) in connection.execute(PRICED, (venue, day))}


STANDING = """
select distinct on (isin) isin, delivery_quantity
from delivery_daily
where venue = %s and trade_date = %s
order by isin, as_of_date desc
"""


def corrected_delivery(
    connection: psycopg.Connection,
    venue: str,
    day: date,
    records: Sequence[DeliveryRecord],
    noticed: date,
) -> list[DeliveryRecord]:
    """The figures of a corrected file that differ from the version standing, dated the day noticed."""
    standing: dict[str, int] = dict(connection.execute(STANDING, (venue, day)).fetchall())
    return [
        record.model_copy(update={"as_of_date": noticed})
        for record in records
        if standing.get(record.isin) != record.delivery_quantity
    ]


def ingest_delivery(
    context: AssetExecutionContext,
    venue: str,
    database: Database,
    deliveries: Deliveries,
    recheck_on: date | None = None,
) -> MaterializeResult[None]:
    window = context.partition_key_range
    definition = deliveries.definition(venue)
    adapter = deliveries.adapter(venue)
    prices = Bhavcopies().definition(venue)
    price_source = prices.source_id

    published = unpublished = failed = written = unpriced = corrected = recheck_failed = 0
    days = list(calendar_days(date.fromisoformat(window.start), date.fromisoformat(window.end)))
    # A delivery figure is stored only beside a bar, so a day the venue's prices are not registered
    # for is outside delivery's coverage too, however far back the delivery file reaches.
    covered = [day for day in days if definition.covers(day) and prices.covers(day)]
    outside_coverage = len(days) - len(covered)

    with database.connect() as connection:
        rechecked = set()
        if recheck_on is not None and days:
            held = latest_days_held(
                connection, venue, days[0], days[-1], RECHECKED_DAYS, "delivery_daily"
            )
            rechecked = set(held)
        for day in covered:
            partition = day.isoformat()
            version = definition.version_for(day)
            if day in rechecked and recheck_on is not None:
                try:
                    adapter.recheck(day, recheck_on)
                except SourceError as failure:
                    recheck_failed += 1
                    context.log.warning(
                        "delivery could not be asked for again",
                        extra={"venue": venue, "trade_date": partition, "detail": str(failure)},
                    )

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

            resolved = adapter.normalize(rows, resolver(connection, venue, day))
            with_bars = priced(connection, venue, day)
            records = [record for record in resolved if record.isin in with_bars]
            if len(records) < len(resolved):
                unpriced += len(resolved) - len(records)
                context.log.info(
                    "delivery for instruments without a bar left out",
                    extra={
                        "venue": venue,
                        "trade_date": partition,
                        "rows": len(resolved) - len(records),
                    },
                )
            written += persist_delivery(connection, records)
            record_ingestion(
                connection, definition.source_id, partition, version, "succeeded", len(records)
            )
            # A corrected file is a version of the day's registered file, read whole before it was
            # held; only what it changed is stored, dated the day it was noticed.
            registered = definition.version_for(day)
            for noticed, file in adapter.corrections(day):
                read = held_to(adapter.parse(file, registered), day, venue)
                resolved = adapter.normalize(read, resolver(connection, venue, day))
                kept = [item for item in resolved if item.isin in with_bars]
                changed = corrected_delivery(connection, venue, day, kept, noticed)
                corrected += persist_delivery(connection, changed)
                record_ingestion(
                    connection,
                    definition.source_id,
                    f"{partition}.as-of-{noticed:%Y%m%d}",
                    registered,
                    "succeeded",
                    len(changed),
                )
            connection.commit()
            published += 1

    context.log.info(
        "delivery ingested",
        extra={
            "venue": venue,
            "published": published,
            "failed": failed,
            "outside_coverage": outside_coverage,
            "written": written,
            "unpriced": unpriced,
            "corrected": corrected,
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
            "written": written,
            "unpriced": unpriced,
            "corrected": corrected,
            "recheck_failed": recheck_failed,
        }
    )


@asset(
    partitions_def=INGESTION_DAYS,
    backfill_policy=BackfillPolicy.single_run(),
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="BSE delivery quantities for each trading day in the run.",
)
def bse_delivery(
    context: AssetExecutionContext, database: Database, deliveries: Deliveries
) -> MaterializeResult[None]:
    return ingest_delivery(context, "BSE", database, deliveries, recheck_day(context))


@asset(
    partitions_def=INGESTION_DAYS,
    backfill_policy=BackfillPolicy.single_run(),
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="NSE delivery quantities for each trading day in the run.",
)
def nse_delivery(
    context: AssetExecutionContext, database: Database, deliveries: Deliveries
) -> MaterializeResult[None]:
    return ingest_delivery(context, "NSE", database, deliveries, recheck_day(context))
