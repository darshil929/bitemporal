"""trading day completeness

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER = "trading_day_is_append_only"


def upgrade() -> None:
    op.create_table(
        "trading_day",
        sa.Column("venue", sa.String(length=12), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("bars", sa.Integer(), nullable=False),
        sa.Column("divergent_instruments", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "venue ~ '^[A-Z][A-Z0-9]{1,11}$'", name=op.f("ck_trading_day_venue_format")
        ),
        sa.CheckConstraint("bars >= 0", name=op.f("ck_trading_day_bars_is_not_negative")),
        sa.CheckConstraint(
            "(is_complete) = (detail is null)",
            name=op.f("ck_trading_day_detail_explains_a_failure"),
        ),
        sa.PrimaryKeyConstraint("venue", "trade_date", "as_of_date", name=op.f("pk_trading_day")),
    )
    op.execute(
        f"create trigger {TRIGGER} before update on trading_day"
        f" for each row execute function reject_fact_update('trading_day')"
    )


def downgrade() -> None:
    op.execute(f"drop trigger {TRIGGER} on trading_day")
    op.drop_table("trading_day")
