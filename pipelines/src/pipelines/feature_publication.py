"""Which of the two daily feature tables readers see.

Readers query the view `mart_daily_features`, which reads one of two tables of the same columns.
"""

import psycopg

from pipelines.db.schema import FEATURE_TABLES, FEATURES_VIEW

# The view's rule depends on the one table it reads.
PUBLISHED = (
    "select distinct dependency.relname from pg_rewrite as rule"
    " inner join pg_depend as link on link.objid = rule.oid"
    " inner join pg_class as dependency on dependency.oid = link.refobjid"
    " where rule.ev_class = %s::regclass and dependency.relname = any(%s)"
)


class FeatureTableUnknown(Exception):
    """The view reads none of the feature tables, or more than one."""


def published_table(connection: psycopg.Connection) -> str:
    rows = connection.execute(PUBLISHED, (FEATURES_VIEW, list(FEATURE_TABLES))).fetchall()
    if len(rows) != 1:
        raise FeatureTableUnknown(f"{FEATURES_VIEW} reads {len(rows)} of the daily feature tables")
    return str(rows[0][0])
