"""Who a request acts for, read from its session cookie, with the session's limits enforced."""

import base64
import binascii
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text

from api.db.database import ACTING_FOR, Database

# A session token is 32 random bytes, carried in the cookie as unpadded base64url and stored as its
# SHA-256 digest.
TOKEN_BYTES = 32

# Activity is recorded at most this often; the shortest idle limit an admin can set is 5 minutes.
ACTIVITY_INTERVAL = timedelta(minutes=1)

Role = Literal["admin", "member"]
EndedReason = Literal["idle", "limit", "signed_out", "signed_out_elsewhere", "disabled"]

SESSION = text(
    "select id, owner_id, created_at, last_seen_at, ended_at, ended_reason"
    " from session_for_token(:token)"
)
STANDING = text(
    "select users.id, users.username, users.display_name, users.role,"
    " users.must_change_password, users.disabled_at,"
    " settings.session_idle_minutes, settings.session_max_hours, now() as now"
    " from app_user as users cross join app_setting as settings where users.id = :owner"
)
END = text("update app_session set ended_at = :at, ended_reason = :reason where id = :id")
SEEN = text("update app_session set last_seen_at = now() where id = :id")
SIGN_OUT = text(
    "update app_session set ended_at = now(), ended_reason = 'signed_out' where id = :id"
)


@dataclass(frozen=True)
class SignedInUser:
    id: int
    username: str
    display_name: str
    role: Role
    must_change_password: bool


@dataclass
class NotSignedIn(Exception):
    """A request with no running session; where it had one, why and when that ended, and the limits."""

    reason: EndedReason | None = None
    ended_at: datetime | None = None
    idle_minutes: int | None = None
    max_hours: int | None = None


def new_token() -> tuple[str, bytes]:
    """A fresh session token: the cookie's value, and the digest stored for it."""
    token = secrets.token_bytes(TOKEN_BYTES)
    return base64.urlsafe_b64encode(token).rstrip(b"=").decode(), hashlib.sha256(token).digest()


def token_hash(cookie: str) -> bytes | None:
    """The stored form of a session token, or None for a value that is not one."""
    try:
        token = base64.urlsafe_b64decode(cookie + "=" * (-len(cookie) % 4))
    except (binascii.Error, ValueError):
        return None
    return hashlib.sha256(token).digest() if len(token) == TOKEN_BYTES else None


def ending(session: Any, standing: Any) -> tuple[EndedReason, datetime] | None:
    """Why and when a running session ends: the earlier of its idle and maximum limits once passed,
    or now where its account is disabled."""
    limit_moments: tuple[tuple[datetime, EndedReason], ...] = (
        (session.last_seen_at + timedelta(minutes=standing.session_idle_minutes), "idle"),
        (session.created_at + timedelta(hours=standing.session_max_hours), "limit"),
    )
    passed = [(moment, reason) for moment, reason in limit_moments if moment <= standing.now]
    if passed:
        moment, reason = min(passed)
        return reason, moment
    return ("disabled", standing.now) if standing.disabled_at is not None else None


async def signed_in_user(database: Database, cookie: str | None) -> SignedInUser:
    """The person the cookie's session acts for, recording the session's activity or its end."""
    hashed = token_hash(cookie) if cookie else None
    if hashed is None:
        raise NotSignedIn
    async with database.transaction() as transaction:
        session = (await transaction.execute(SESSION, {"token": hashed})).one_or_none()
        if session is None:
            raise NotSignedIn
        await transaction.execute(ACTING_FOR, {"user": str(session.owner_id)})
        standing = (await transaction.execute(STANDING, {"owner": session.owner_id})).one()
        limits = (standing.session_idle_minutes, standing.session_max_hours)
        if session.ended_at is not None:
            raise NotSignedIn(session.ended_reason, session.ended_at, *limits)
        ended = ending(session, standing)
        if ended is not None:
            await transaction.execute(END, {"id": session.id, "at": ended[1], "reason": ended[0]})
        elif standing.now - session.last_seen_at >= ACTIVITY_INTERVAL:
            await transaction.execute(SEEN, {"id": session.id})
    # The end is recorded before the request is refused.
    if ended is not None:
        raise NotSignedIn(*ended, *limits)
    return SignedInUser(
        id=standing.id,
        username=standing.username,
        display_name=standing.display_name,
        role=standing.role,
        must_change_password=standing.must_change_password,
    )


async def sign_out(database: Database, cookie: str | None) -> None:
    """End the cookie's session where it is still running; a cookie naming none changes nothing."""
    hashed = token_hash(cookie) if cookie else None
    if hashed is None:
        return
    async with database.transaction() as transaction:
        session = (await transaction.execute(SESSION, {"token": hashed})).one_or_none()
        if session is None or session.ended_at is not None:
            return
        await transaction.execute(ACTING_FOR, {"user": str(session.owner_id)})
        await transaction.execute(SIGN_OUT, {"id": session.id})
