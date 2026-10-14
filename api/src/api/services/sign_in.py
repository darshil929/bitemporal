"""Signing in with a password, and the pause that slows repeated wrong ones."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import text

from api.db.database import Database
from api.services.passwords import unmatched_hash, verify
from api.services.sessions import SignedInUser, new_token

# Wrong passwords allowed before the first pause; each one after it doubles the pause, up to the
# longest. Attempts during a pause are refused unchecked and uncounted, so no one keeps another
# person paused for longer than the longest pause.
FREE_FAILURES = 4
FIRST_PAUSE = timedelta(minutes=1)
LONGEST_PAUSE = timedelta(hours=1)

# The start of the browser's User-Agent kept with the session, enough to tell devices apart.
USER_AGENT_LENGTH = 200

SignInRefusal = Literal["wrong_credentials", "paused", "disabled", "temporary_password_expired"]

CANDIDATE = text("select *, now() as now from sign_in_candidate(:username)")
RECORD_FAILURE = text("select record_failed_sign_in(:account, :until)")
START = text(
    "insert into app_session (owner_id, token_hash, user_agent_summary)"
    " values (:owner, :token, :agent)"
)
CLEAR_FAILURES = text(
    "update app_user set failed_sign_ins = 0, sign_in_paused_until = null"
    " where id = :id and (failed_sign_ins > 0 or sign_in_paused_until is not null)"
)
REHASH = text("update app_user set password_hash = :hash where id = :id")
ACCOUNT = text(
    "select users.id, users.username, users.display_name, users.role,"
    " users.must_change_password, settings.session_max_hours"
    " from app_user as users cross join app_setting as settings where users.id = :id"
)


@dataclass
class SignInRefused(Exception):
    reason: SignInRefusal
    paused_until: datetime | None = None


@dataclass(frozen=True)
class SignedIn:
    user: SignedInUser
    cookie: str
    max_hours: int


def pause_after(failures: int) -> timedelta | None:
    """How long sign-in pauses after this many consecutive wrong passwords."""
    if failures <= FREE_FAILURES:
        return None
    return min(FIRST_PAUSE * (1 << (failures - FREE_FAILURES - 1)), LONGEST_PAUSE)


async def sign_in(
    database: Database, username: str, password: str, user_agent: str | None
) -> SignedIn:
    """A new session for the account the password opens. A wrong username and a wrong password are
    refused alike; a disabled account, or a temporary password past its day, is named only once the
    password is right."""
    async with database.transaction() as transaction:
        candidate = (await transaction.execute(CANDIDATE, {"username": username})).one_or_none()
    if candidate is None:
        await verify(password, unmatched_hash())
        raise SignInRefused("wrong_credentials")
    if candidate.sign_in_paused_until and candidate.sign_in_paused_until > candidate.now:
        raise SignInRefused("paused", candidate.sign_in_paused_until)

    matches, rehashed = await verify(password, candidate.password_hash)
    if not matches:
        pause = pause_after(candidate.failed_sign_ins + 1)
        until = candidate.now + pause if pause else None
        async with database.transaction() as transaction:
            await transaction.execute(RECORD_FAILURE, {"account": candidate.id, "until": until})
        raise SignInRefused("paused", until) if until else SignInRefused("wrong_credentials")
    if candidate.disabled_at is not None:
        raise SignInRefused("disabled")
    expires = candidate.temporary_password_expires_at
    if candidate.must_change_password and expires is not None and expires <= candidate.now:
        raise SignInRefused("temporary_password_expired")

    cookie, token_hash = new_token()
    agent = user_agent[:USER_AGENT_LENGTH] if user_agent else None
    async with database.transaction(candidate.id) as transaction:
        await transaction.execute(
            START, {"owner": candidate.id, "token": token_hash, "agent": agent}
        )
        await transaction.execute(CLEAR_FAILURES, {"id": candidate.id})
        if rehashed is not None:
            await transaction.execute(REHASH, {"id": candidate.id, "hash": rehashed})
        account = (await transaction.execute(ACCOUNT, {"id": candidate.id})).one()
    # The account's first five columns are the signed-in person's, in order.
    return SignedIn(SignedInUser(*account[:5]), cookie, account.session_max_hours)
