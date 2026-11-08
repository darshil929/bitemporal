"""watchlist alert evaluations

Each alert's verdict on a session its entry's venue published: triggered, watching or paused, with
the figure its rule compared. Rows are appended, never changed; a figure corrected after its session
was judged is judged again under the later as-of date. Row security, forced, shows the API's role a
person's own verdicts alone, which it reads and does not write; a verdict belongs to an alert of the
same person.

Revision ID: 0027
Revises: 0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
TABLE = "watchlist_alert_evaluation"
TRIGGER = f"{TABLE}_is_append_only"
OWN = "owner_id = (select nullif(current_setting('app.user_id', true), '')::bigint)"
STATUSES = ("triggered", "watching", "paused")
PAUSED_REASONS = ("not_traded", "capital_action")


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_watchlist_alert_id_owner_id"), "watchlist_alert", ["id", "owner_id"]
    )
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("figure", sa.Double(), nullable=True),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"status in {STATUSES}", name=op.f(f"ck_{TABLE}_status")),
        sa.CheckConstraint(
            f"paused_reason is null or paused_reason in {PAUSED_REASONS}",
            name=op.f(f"ck_{TABLE}_paused_reason"),
        ),
        sa.CheckConstraint(
            "(status = 'paused') = (paused_reason is not null)",
            name=op.f(f"ck_{TABLE}_paused_with_reason"),
        ),
        sa.CheckConstraint("as_of_date >= trade_date", name=op.f(f"ck_{TABLE}_known_after")),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"], name=op.f(f"fk_{TABLE}_owner_id")),
        sa.ForeignKeyConstraint(
            ["alert_id", "owner_id"],
            ["watchlist_alert.id", "watchlist_alert.owner_id"],
            name=op.f(f"fk_{TABLE}_alert_id_owner_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint(
            "owner_id",
            "alert_id",
            "trade_date",
            "as_of_date",
            name=op.f(f"uq_{TABLE}_owner_id_alert_id_trade_date_as_of_date"),
        ),
    )
    op.create_index(op.f(f"ix_{TABLE}_owner_id"), TABLE, ["owner_id"])
    op.execute(
        f"create trigger {TRIGGER} before update on {TABLE}"
        f" for each row execute function reject_fact_update('{TABLE}')"
    )
    op.execute(f"alter table {TABLE} enable row level security")
    op.execute(f"alter table {TABLE} force row level security")
    op.execute(f"create policy own_only on {TABLE} for all using ({OWN}) with check ({OWN})")
    op.execute(f"grant select on {TABLE} to {ROLE}")


def downgrade() -> None:
    op.execute(f"drop trigger {TRIGGER} on {TABLE}")
    op.drop_table(TABLE)
    op.drop_constraint(op.f("uq_watchlist_alert_id_owner_id"), "watchlist_alert", type_="unique")
