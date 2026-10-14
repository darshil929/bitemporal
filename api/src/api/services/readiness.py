"""Whether the database answers and holds the schema the API's queries are written against."""

import logging
from dataclasses import dataclass

from psycopg.errors import InsufficientPrivilege, UndefinedTable
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from api.db.database import Database

logger = logging.getLogger(__name__)

# The migration the API's queries are written against.
EXPECTED_REVISION = "0020"

CURRENT_REVISION = text("select version_num from alembic_version")

# The role the API connects as, and what would let it read past row security: being a superuser,
# bypassing it, or owning a relation in the schema, which row security binds only where forced.
ROLE_STANDING = text(
    "select current_user, rolsuper, rolbypassrls,"
    " (select count(*) from pg_class"
    " where relowner = pg_roles.oid and relnamespace = current_schema()::regnamespace)"
    " from pg_roles where rolname = current_user"
)


@dataclass(frozen=True)
class Readiness:
    is_ready: bool
    schema: str
    revision: str | None
    reason: str | None


def privilege(role: str, is_superuser: bool, bypasses: bool, owned: int, schema: str) -> str | None:
    """Why the role would read rows row security keeps from it, or None where nothing would."""
    if is_superuser or bypasses:
        return f"the API connects as {role}, which reads past row security"
    if owned:
        return f"the API connects as {role}, which owns {owned} relations in schema {schema}"
    return None


async def check_readiness(database: Database) -> Readiness:
    try:
        async with database.transaction() as session:
            role, is_superuser, bypasses, owned = (await session.execute(ROLE_STANDING)).one()
            if reason := privilege(role, is_superuser, bypasses, owned, database.schema):
                return not_ready(database.schema, None, reason)
            revision = (await session.execute(CURRENT_REVISION)).scalar_one_or_none()
    except OperationalError:
        return not_ready(database.schema, None, "the database does not answer")
    except ProgrammingError as error:
        if isinstance(error.orig, UndefinedTable):
            return not_ready(
                database.schema, None, f"schema {database.schema} records no migration"
            )
        if isinstance(error.orig, InsufficientPrivilege):
            return not_ready(
                database.schema, None, f"the API's role may not read schema {database.schema}"
            )
        raise

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
