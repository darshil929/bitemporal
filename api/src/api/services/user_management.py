"""The people an admin manages: their accounts, each added with a temporary password, and the
changes to an account's role, state and password."""

from dataclasses import dataclass
from datetime import datetime

import anyio
from psycopg.errors import RestrictViolation, UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.audit import AdminAction, record_admin_action
from api.services.passwords import hash_password
from api.services.sessions import Role
from api.services.temporary_passwords import TEMPORARY_PASSWORD_LIFETIME, temporary_password

COLUMNS = (
    "users.id, users.username, users.display_name, users.role, users.disabled_at,"
    " users.must_change_password, users.created_at"
)
LAST_SIGNED_IN = (
    "(select max(sessions.created_at) from app_session as sessions"
    " where sessions.owner_id = users.id) as last_signed_in"
)
PEOPLE = text(
    f"select {COLUMNS}, {LAST_SIGNED_IN} from app_user as users"
    " order by users.created_at desc, users.id desc"
)
PERSON = text(f"select {COLUMNS}, {LAST_SIGNED_IN} from app_user as users where users.id = :id")
CHANGE_ROLE = text("update app_user set role = :role where id = :id")
DISABLE = text("update app_user set disabled_at = now() where id = :id")
ENABLE = text("update app_user set disabled_at = null where id = :id")
RESET = text(
    "update app_user set password_hash = :hash, must_change_password = true,"
    " temporary_password_expires_at = now() + :lifetime, failed_sign_ins = 0,"
    " sign_in_paused_until = null where id = :id"
)
END_SESSIONS = text(
    "update app_session set ended_at = now(), ended_reason = :reason"
    " where owner_id = :id and ended_at is null"
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
class IssuedPassword:
    """An account, and the temporary password just issued for it, shown this once."""

    person: Person
    temporary_password: str


@dataclass
class PersonRefused(Exception):
    """A change refused: a username taken, no such account, an admin disabling their own account,
    or one that would leave no enabled admin."""

    reason: str


async def person(transaction: AsyncSession, person_id: int) -> Person:
    found = (await transaction.execute(PERSON, {"id": person_id})).one_or_none()
    if found is None:
        raise PersonRefused("person_not_found")
    return Person(*found)


async def people(database: Database, admin_id: int) -> tuple[Person, ...]:
    """Every account, newest first, with when each person last signed in."""
    async with database.transaction(admin_id) as transaction:
        return tuple(Person(*row) for row in await transaction.execute(PEOPLE))


async def add_person(
    database: Database, admin_id: int, username: str, display_name: str, role: Role
) -> IssuedPassword:
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
            added = Person(*(await transaction.execute(ADD, values)).one())
            await record_admin_action(
                transaction, admin_id, "person_added", subject_id=added.id, detail={"role": role}
            )
    except IntegrityError as error:
        if isinstance(error.orig, UniqueViolation):
            raise PersonRefused("username_taken") from error
        raise
    return IssuedPassword(added, password)


async def change_account(
    database: Database, admin_id: int, person_id: int, role: Role | None, disabled: bool | None
) -> Person:
    """Change an account's role or whether it is enabled; disabling it ends its sessions at once.
    Each change made is recorded, and a value already held changes nothing."""
    if disabled and person_id == admin_id:
        raise PersonRefused("own_account")
    try:
        # Each change is recorded before it is made, as only an admin records one and an admin may
        # be giving up the role.
        async with database.transaction(admin_id) as transaction:
            current = await person(transaction, person_id)
            if role is not None and role != current.role:
                change = {"from": current.role, "to": role}
                await record_admin_action(
                    transaction, admin_id, "role_changed", subject_id=person_id, detail=change
                )
                await transaction.execute(CHANGE_ROLE, {"id": person_id, "role": role})
            if disabled is not None and disabled != (current.disabled_at is not None):
                action: AdminAction = "account_disabled" if disabled else "account_enabled"
                await record_admin_action(transaction, admin_id, action, subject_id=person_id)
                await transaction.execute(DISABLE if disabled else ENABLE, {"id": person_id})
                if disabled:
                    await transaction.execute(END_SESSIONS, {"id": person_id, "reason": "disabled"})
            return await person(transaction, person_id)
    except DBAPIError as error:
        # The database keeps an enabled admin, refusing the change that would leave none.
        if isinstance(error.orig, RestrictViolation):
            raise PersonRefused("last_admin") from error
        raise


async def reset_password(database: Database, admin_id: int, person_id: int) -> IssuedPassword:
    """Replace an account's password with a temporary one, clear its failed sign-ins and end its
    sessions, so a session opened before the reset ends with it."""
    async with database.transaction(admin_id) as transaction:
        current = await person(transaction, person_id)
    password = temporary_password(current.username, current.display_name)
    hashed = await anyio.to_thread.run_sync(hash_password, password)
    values = {"id": person_id, "hash": hashed, "lifetime": TEMPORARY_PASSWORD_LIFETIME}
    async with database.transaction(admin_id) as transaction:
        await transaction.execute(RESET, values)
        await transaction.execute(END_SESSIONS, {"id": person_id, "reason": "signed_out_elsewhere"})
        await record_admin_action(transaction, admin_id, "password_reset", subject_id=person_id)
        return IssuedPassword(await person(transaction, person_id), password)
