"""flow requests

An admin's request for a run of the history bootstrap or the daily sync over a range of days. The
flows pick a request up, refuse it with the reason and its facts or start its run, and record when it
started and finished; a request is one row, changed as it moves on. Row security, forced, lets
anyone signed in read requests and an admin add only requests naming themselves; the API's role
reads and adds. A recorded run names the request that started it.

Revision ID: 0029
Revises: 0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
TABLE = "flow_request"
SIGNED_IN = "(select nullif(current_setting('app.user_id', true), '')::bigint)"
IS_ADMIN = "(select app_user_is_admin())"
FLOWS = ("bootstrap", "sync")
STATUSES = ("requested", "started", "refused", "finished")

# Each policy: name, command, the rows it reaches, the rows it may leave.
POLICIES = (
    ("signed_in_reads", "select", "true", None),
    ("admin_requests_own", "insert", None, f"requested_by = {SIGNED_IN} and {IS_ADMIN}"),
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("flow", sa.Text(), nullable=False),
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="requested", nullable=False),
        sa.Column("refusal", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"flow in {FLOWS}", name=op.f(f"ck_{TABLE}_flow")),
        sa.CheckConstraint(f"status in {STATUSES}", name=op.f(f"ck_{TABLE}_status")),
        sa.CheckConstraint("last_day >= first_day", name=op.f(f"ck_{TABLE}_days")),
        sa.CheckConstraint(
            "(status = 'refused') = (refusal is not null)", name=op.f(f"ck_{TABLE}_refused_why")
        ),
        sa.CheckConstraint(
            "(status in ('started', 'finished')) = (started_at is not null)",
            name=op.f(f"ck_{TABLE}_started"),
        ),
        sa.CheckConstraint(
            "(status = 'finished') = (finished_at is not null)", name=op.f(f"ck_{TABLE}_finished")
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["app_user.id"], name=op.f(f"fk_{TABLE}_requested_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(op.f(f"ix_{TABLE}_status"), TABLE, ["status"])
    op.execute(f"alter table {TABLE} enable row level security")
    op.execute(f"alter table {TABLE} force row level security")
    for name, command, using, check in POLICIES:
        reach = f" using ({using})" if using else ""
        leave = f" with check ({check})" if check else ""
        op.execute(f"create policy {name} on {TABLE} for {command}{reach}{leave}")
    # The time and the status are the database's; the flows move a request on.
    op.execute(
        f"grant select, insert (flow, first_day, last_day, requested_by) on {TABLE} to {ROLE}"
    )
    op.add_column("flow_run", sa.Column("request_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(op.f("fk_flow_run_request_id"), "flow_run", TABLE, ["request_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint(op.f("fk_flow_run_request_id"), "flow_run", type_="foreignkey")
    op.drop_column("flow_run", "request_id")
    op.drop_table(TABLE)
