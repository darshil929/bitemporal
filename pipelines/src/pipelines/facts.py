"""Append-only writes of the facts a venue publishes.

Every write here is an insert. A republished bar carries a later `as_of_date` and lands beside the
version it corrects, and rewriting a partition already stored changes nothing, so an asset can be
re-run for a date without producing a different result.

`price_daily`, `delivery_daily` and `corporate_action` all reference `instrument_master`, so
identity is written before any of them.
"""

import logging
from collections.abc import Sequence

import psycopg

from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.models.market import DeliveryRecord, PriceBar

logger = logging.getLogger(__name__)

BAR_COLUMNS = (
    "isin, venue, trade_date, as_of_date, local_symbol, scrip_code, open, high, low, close,"
    " previous_close, volume, turnover, trade_count"
)
BAR_KEY = "(isin, venue, trade_date, as_of_date)"

DELIVERY_COLUMNS = "isin, venue, trade_date, as_of_date, delivery_quantity"
DELIVERY_KEY = "(isin, venue, trade_date, as_of_date)"

ACTION_COLUMNS = (
    "isin, action_type, ex_date, source_id, as_of_date, qualifier, ratio_from, ratio_to,"
    " dividend_amount, purpose"
)
ACTION_KEY = "(isin, action_type, ex_date, source_id, as_of_date, qualifier)"


def _append(
    connection: psycopg.Connection,
    table: str,
    columns: str,
    key: str,
    rows: Sequence[tuple[object, ...]],
) -> int:
    """Insert rows, leaving any version already stored untouched, and count those written.

    The rows of one trading day go in a single statement. A day carries a few thousand bars and
    a full history carries thousands of days, so a round trip per row is what a backfill spends
    most of its time on.
    """
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(rows[0]))
    statement = (
        f"insert into {table} ({columns}) values ({placeholders}) on conflict {key} do nothing"
    )

    with connection.cursor() as cursor:
        cursor.executemany(statement, rows)
        # Rows already stored conflict and are not counted, so this is what the day added.
        return cursor.rowcount


def persist_bars(connection: psycopg.Connection, bars: Sequence[PriceBar]) -> int:
    rows = [
        (
            bar.isin,
            bar.venue,
            bar.trade_date,
            bar.as_of_date,
            bar.local_symbol,
            bar.scrip_code,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.previous_close,
            bar.volume,
            bar.turnover,
            bar.trade_count,
        )
        for bar in bars
    ]
    written = _append(connection, "price_daily", BAR_COLUMNS, BAR_KEY, rows)

    logger.info("bars written", extra={"offered": len(rows), "written": written})
    return written


def persist_delivery(connection: psycopg.Connection, records: Sequence[DeliveryRecord]) -> int:
    rows = [
        (record.isin, record.venue, record.trade_date, record.as_of_date, record.delivery_quantity)
        for record in records
    ]
    written = _append(connection, "delivery_daily", DELIVERY_COLUMNS, DELIVERY_KEY, rows)

    logger.info("delivery written", extra={"offered": len(rows), "written": written})
    return written


def persist_actions(
    connection: psycopg.Connection, actions: Sequence[CorporateActionRecord]
) -> int:
    rows = [
        (
            action.isin,
            action.action_type,
            action.ex_date,
            action.source_id,
            action.as_of_date,
            action.qualifier,
            action.ratio_from,
            action.ratio_to,
            action.dividend_amount,
            action.purpose,
        )
        for action in actions
    ]
    written = _append(connection, "corporate_action", ACTION_COLUMNS, ACTION_KEY, rows)

    logger.info("corporate actions written", extra={"offered": len(rows), "written": written})
    return written


def record_ingestion(
    connection: psycopg.Connection,
    source_id: str,
    partition_key: str,
    schema_version: str,
    outcome: str,
    row_count: int | None = None,
    detail: str | None = None,
) -> None:
    """Record one attempt to read a slice of a source, whatever came of it.

    A day a venue never published is an outcome of its own rather than a failure, and the log is
    what separates the two when a gap is investigated later.
    """
    connection.execute(
        "insert into ingestion_log"
        " (source_id, partition_key, schema_version, outcome, row_count, detail)"
        " values (%s, %s, %s, %s, %s, %s)",
        (source_id, partition_key, schema_version, outcome, row_count, detail),
    )

    logger.info(
        "ingestion recorded",
        extra={
            "source_id": source_id,
            "partition_key": partition_key,
            "outcome": outcome,
            "row_count": row_count,
        },
    )
