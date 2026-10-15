"""The record of every change an admin makes, which admins alone read."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database

RECENT_ACTIONS = 50

AdminAction = Literal[
    "first_admin_created",
    "person_added",
    "role_changed",
    "account_disabled",
    "account_enabled",
    "password_reset",
    "session_limits_changed",
    "sync_started",
    "bootstrap_started",
    "run_cancelled",
]

RECORD = text(
    "insert into audit_event (actor_id, action, subject_id, detail)"
    " values (:actor, :action, :subject, cast(:detail as jsonb))"
)
RECENT = text(
    "select events.occurred_at, events.actor_id, actors.display_name as actor_name, events.action,"
    " events.subject_id, subjects.display_name as subject_name, events.detail"
    " from audit_event as events"
    " inner join app_user as actors on events.actor_id = actors.id"
    " left join app_user as subjects on events.subject_id = subjects.id"
    " order by events.occurred_at desc, events.id desc limit :limit"
)


@dataclass(frozen=True)
class AuditEntry:
    occurred_at: datetime
    actor_id: int
    actor_name: str
    action: AdminAction
    subject_id: int | None
    subject_name: str | None
    detail: dict[str, Any]


async def record_admin_action(
    transaction: AsyncSession,
    actor_id: int,
    action: AdminAction,
    subject_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Record the action in the transaction that makes the change, so neither stands without the
    other; the transaction acts for the admin."""
    values = {"actor": actor_id, "action": action, "subject": subject_id}
    await transaction.execute(RECORD, values | {"detail": json.dumps(detail or {})})


async def recent_admin_actions(database: Database, admin_id: int) -> tuple[AuditEntry, ...]:
    """The newest actions, newest first, with the names of who acted and on whom."""
    async with database.transaction(admin_id) as transaction:
        rows = await transaction.execute(RECENT, {"limit": RECENT_ACTIONS})
        return tuple(AuditEntry(*row) for row in rows)
