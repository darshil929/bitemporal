"""Whether the database answers and holds the schema the API's queries are written against."""

import logging
from dataclasses import dataclass

from psycopg.errors import UndefinedTable
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from api.db.database import Database

logger = logging.getLogger(__name__)

# The migration the API's queries are written against.
EXPECTED_REVISION = "0018"

CURRENT_REVISION = text("select version_num from alembic_version")


@dataclass(frozen=True)
class Readiness:
    is_ready: bool
    schema: str
    revision: str | None
    reason: str | None


async def check_readiness(database: Database) -> Readiness:
    try:
        async with database.transaction() as session:
            revision = (await session.execute(CURRENT_REVISION)).scalar_one_or_none()
    except OperationalError:
        return not_ready(database.schema, None, "the database does not answer")
    except ProgrammingError as error:
        if not isinstance(error.orig, UndefinedTable):
            raise
        return not_ready(database.schema, None, f"schema {database.schema} records no migration")

    if revision != EXPECTED_REVISION:
        reason = (
            f"schema {database.schema} is at migration {revision},"
            f" the API expects {EXPECTED_REVISION}"
        )
        return not_ready(database.schema, revision, reason)
    return Readiness(is_ready=True, schema=database.schema, revision=revision, reason=None)


def not_ready(schema: str, revision: str | None, reason: str) -> Readiness:
    logger.warning(
        "database not ready",
        extra={"schema": schema, "revision": revision, "expected_revision": EXPECTED_REVISION},
    )
    return Readiness(is_ready=False, schema=schema, revision=revision, reason=reason)
