"""admin action audit

Every change an admin makes is recorded and never changed. Row security, forced, shows the records
to admins alone and lets an admin add only records naming themselves as the one who acted; the
API's role reads and adds, and a trigger refuses any change to a recorded row.

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
TABLE = "audit_event"
SIGNED_IN = "(select nullif(current_setting('app.user_id', true), '')::bigint)"
IS_ADMIN = "(select app_user_is_admin())"
ACTIONS = (
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
)

# Each policy: name, command, the rows it reaches, the rows it may leave.
POLICIES = (
    ("admin_reads", "select", IS_ADMIN, None),
    ("admin_records_own", "insert", None, f"actor_id = {SIGNED_IN} and {IS_ADMIN}"),
)


def upgrade() -> None:
    listed = ", ".join(f"'{action}'" for action in ACTIONS)
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(f"action in ({listed})", name=op.f("ck_audit_event_action")),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["app_user.id"], name=op.f("fk_audit_event_actor_id")
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["app_user.id"], name=op.f("fk_audit_event_subject_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_event")),
    )
    op.create_index(op.f("ix_audit_event_occurred_at"), TABLE, ["occurred_at"])
    op.execute(
        f"create trigger audit_event_is_append_only before update on {TABLE}"
        f" for each row execute function reject_fact_update('{TABLE}')"
    )
    op.execute(f"alter table {TABLE} enable row level security")
    op.execute(f"alter table {TABLE} force row level security")
    for name, command, using, check in POLICIES:
        reach = f" using ({using})" if using else ""
        leave = f" with check ({check})" if check else ""
        op.execute(f"create policy {name} on {TABLE} for {command}{reach}{leave}")
    # The time is the database's; the API names everything else.
    op.execute(f"grant select, insert (actor_id, action, subject_id, detail) on {TABLE} to {ROLE}")


def downgrade() -> None:
    op.drop_table(TABLE)
