"""Which of the two daily feature tables readers see, and the switch to the other.

Readers query the view `mart_daily_features`, which reads one of two tables of the same columns. A
computation is written into the table the view does not read and then published by pointing the
view at it, so no reader waits for a write and the previous computation stays in place until the
next one is written over it. Each publish is recorded in `feature_release`.
"""

import logging
from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg import sql

from pipelines.db.schema import FEATURE_TABLES, FEATURES_VIEW

logger = logging.getLogger(__name__)

# Pointing the view at a table waits for the view's readers to finish, and every reader arriving
# meanwhile waits behind it, so each attempt gives up after this long and the next starts anew.
LOCK_TIMEOUT = "500ms"
PUBLISH_ATTEMPTS = 20

# The view's rule depends on the one table it reads.
PUBLISHED = (
    "select distinct dependency.relname from pg_rewrite as rule"
    " inner join pg_depend as link on link.objid = rule.oid"
    " inner join pg_class as dependency on dependency.oid = link.refobjid"
    " where rule.ev_class = %s::regclass and dependency.relname = any(%s)"
)

RECORD = (
    "insert into feature_release (table_name, trade_date, row_count, run_id)"
    " values (%s, %s, %s, %s) returning release_id"
)


class FeatureTableUnknown(Exception):
    """The view reads none of the feature tables, or more than one."""


class PublicationRefused(Exception):
    """Readers held the view through every attempt to publish."""


@dataclass(frozen=True)
class Release:
    release_id: int
    table_name: str
    trade_date: date | None
    row_count: int


def published_table(connection: psycopg.Connection) -> str:
    rows = connection.execute(PUBLISHED, (FEATURES_VIEW, list(FEATURE_TABLES))).fetchall()
    if len(rows) != 1:
        raise FeatureTableUnknown(f"{FEATURES_VIEW} reads {len(rows)} of the daily feature tables")
    return str(rows[0][0])


def unpublished_table(connection: psycopg.Connection) -> str:
    published = published_table(connection)
    return next(table for table in FEATURE_TABLES if table != published)


def publish(
    connection: psycopg.Connection,
    table: str,
    run_id: str | None,
    attempts: int = PUBLISH_ATTEMPTS,
    lock_timeout: str = LOCK_TIMEOUT,
) -> Release:
    """Point the view at `table` and record the release, retrying while readers hold the view."""
    newest, rows = connection.execute(
        sql.SQL("select max(trade_date), count(*) from {}").format(sql.Identifier(table))
    ).fetchone() or (None, 0)
    repoint = sql.SQL("create or replace view {} as select * from {}").format(
        sql.Identifier(FEATURES_VIEW), sql.Identifier(table)
    )
    for attempt in range(1, attempts + 1):
        try:
            with connection.transaction():
                connection.execute("select set_config('lock_timeout', %s, true)", (lock_timeout,))
                connection.execute(repoint)
                recorded = connection.execute(RECORD, (table, newest, rows, run_id)).fetchone()
        except psycopg.errors.LockNotAvailable:
            logger.warning(
                "daily feature publication waited on readers",
                extra={"table": table, "attempt": attempt, "attempts": attempts},
            )
            continue
        release_id = int(recorded[0]) if recorded else 0
        logger.info(
            "daily features published",
            extra={"table": table, "trade_date": newest, "rows": rows, "release_id": release_id},
        )
        return Release(release_id, table, newest, int(rows))
    raise PublicationRefused(
        f"readers held {FEATURES_VIEW} through {attempts} attempts to publish {table}"
    )
