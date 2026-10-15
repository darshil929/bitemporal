"""The people an admin manages: their accounts, each added with a temporary password."""

from dataclasses import dataclass
from datetime import datetime

import anyio
from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.db.database import Database
from api.services.audit import record_admin_action
from api.services.passwords import hash_password
from api.services.sessions import Role
from api.services.temporary_passwords import TEMPORARY_PASSWORD_LIFETIME, temporary_password

COLUMNS = (
    "users.id, users.username, users.display_name, users.role, users.disabled_at,"
    " users.must_change_password, users.created_at"
)
PEOPLE = text(
    f"select {COLUMNS}, (select max(sessions.created_at) from app_session as sessions"
    " where sessions.owner_id = users.id) as last_signed_in"
    " from app_user as users order by users.created_at desc, users.id desc"
)
# Usernames are kept in lower case, so one matches whatever case it is typed in.
ADD = text(
    "insert into app_user as users (username, display_name, role, password_hash,"
    " must_change_password, temporary_password_expires_at)"
    " values (lower(:username), :display_name, :role, :hash, true, now() + :lifetime)"
    f" returning {COLUMNS}, null::timestamptz as last_signed_in"
)


@dataclass(frozen=True)
class Person:
    id: int
    username: str
    display_name: str
    role: Role
    disabled_at: datetime | None
    must_change_password: bool
    created_at: datetime
    last_signed_in: datetime | None


@dataclass(frozen=True)
class AddedPerson:
    """A person just added, and the temporary password they sign in with, shown this once."""

    person: Person
    temporary_password: str


@dataclass
class PersonRefused(Exception):
    reason: str


async def people(database: Database, admin_id: int) -> tuple[Person, ...]:
    """Every account, newest first, with when each person last signed in."""
    async with database.transaction(admin_id) as transaction:
        return tuple(Person(*row) for row in await transaction.execute(PEOPLE))


async def add_person(
    database: Database, admin_id: int, username: str, display_name: str, role: Role
) -> AddedPerson:
    password = temporary_password(username, display_name)
    hashed = await anyio.to_thread.run_sync(hash_password, password)
    values = {
        "username": username,
        "display_name": display_name,
        "role": role,
        "hash": hashed,
        "lifetime": TEMPORARY_PASSWORD_LIFETIME,
    }
    try:
        async with database.transaction(admin_id) as transaction:
            person = Person(*(await transaction.execute(ADD, values)).one())
            await record_admin_action(
                transaction, admin_id, "person_added", subject_id=person.id, detail={"role": role}
            )
    except IntegrityError as error:
        if isinstance(error.orig, UniqueViolation):
            raise PersonRefused("username_taken") from error
        raise
    return AddedPerson(person, password)
