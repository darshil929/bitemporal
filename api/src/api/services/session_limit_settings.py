"""How long a session may go unused and how long it may last at most, which an admin sets for
everyone; a running session is held to the limits in force at each request."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from api.db.database import Database
from api.services.audit import record_admin_action

LIMITS = text("select session_idle_minutes, session_max_hours, updated_at from app_setting")
CHANGE = text(
    "update app_setting set session_idle_minutes = :idle_minutes,"
    " session_max_hours = :max_hours, updated_at = now()"
)


@dataclass(frozen=True)
class SessionLimits:
    session_idle_minutes: int
    session_max_hours: int
    updated_at: datetime


async def session_limits(database: Database, admin_id: int) -> SessionLimits:
    async with database.transaction(admin_id) as transaction:
        return SessionLimits(*(await transaction.execute(LIMITS)).one())


async def change_session_limits(
    database: Database, admin_id: int, idle_minutes: int | None, max_hours: int | None
) -> SessionLimits:
    """Set either limit; the change is recorded with each limit's value before and after, and a
    value already in force changes nothing."""
    async with database.transaction(admin_id) as transaction:
        current = SessionLimits(*(await transaction.execute(LIMITS)).one())
        wanted = {
            "idle_minutes": (current.session_idle_minutes, idle_minutes),
            "max_hours": (current.session_max_hours, max_hours),
        }
        changed: dict[str, Any] = {
            name: {"from": before, "to": after}
            for name, (before, after) in wanted.items()
            if after is not None and after != before
        }
        if not changed:
            return current
        await record_admin_action(transaction, admin_id, "session_limits_changed", detail=changed)
        values = {
            name: (after if after is not None else before)
            for name, (before, after) in wanted.items()
        }
        await transaction.execute(CHANGE, values)
        return SessionLimits(*(await transaction.execute(LIMITS)).one())
