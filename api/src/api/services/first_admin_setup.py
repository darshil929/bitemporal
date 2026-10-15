"""The installation's first admin, created while no admin exists."""

from dataclasses import dataclass

import anyio
from psycopg.errors import RaiseException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.db.database import ACTING_FOR, Database
from api.services.audit import record_admin_action
from api.services.passwords import hash_password, password_problem
from api.services.sign_in import SignedIn, open_session

ADMIN_EXISTS = text("select an_admin_exists()")
CREATE_FIRST_ADMIN = text("select create_first_admin(:username, :display_name, :hash)")


@dataclass
class SetupRefused(Exception):
    """A first admin the password rule does not admit, or one an admin already precedes."""

    reason: str


async def admin_exists(database: Database) -> bool:
    async with database.transaction() as transaction:
        return bool((await transaction.execute(ADMIN_EXISTS)).scalar_one())


async def create_first_admin(
    database: Database, username: str, display_name: str, password: str, user_agent: str | None
) -> SignedIn:
    """Create the first admin and sign them in; refused once any admin exists."""
    if problem := password_problem(password, username, display_name):
        raise SetupRefused(problem)
    hashed = await anyio.to_thread.run_sync(hash_password, password)
    values = {"username": username, "display_name": display_name, "hash": hashed}
    try:
        async with database.transaction() as transaction:
            admin = (await transaction.execute(CREATE_FIRST_ADMIN, values)).scalar_one()
            await transaction.execute(ACTING_FOR, {"user": str(admin)})
            await record_admin_action(transaction, admin, "first_admin_created", subject_id=admin)
            return await open_session(transaction, admin, user_agent)
    except DBAPIError as error:
        # The function raises once an admin exists, under a lock no second setup gets past.
        if isinstance(error.orig, RaiseException):
            raise SetupRefused("admin_exists") from error
        raise
