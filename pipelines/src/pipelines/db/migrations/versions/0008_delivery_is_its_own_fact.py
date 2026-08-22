"""delivery is its own fact

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER = "delivery_daily_is_append_only"


def upgrade() -> None:
    op.drop_column("price_daily", "delivery_quantity")

    op.create_table(
        "delivery_daily",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("venue", sa.String(length=12), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("delivery_quantity", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "venue ~ '^[A-Z][A-Z0-9]{1,11}$'", name=op.f("ck_delivery_daily_venue_format")
        ),
        sa.CheckConstraint(
            "delivery_quantity >= 0", name=op.f("ck_delivery_daily_quantity_is_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_delivery_daily_isin")
        ),
        sa.PrimaryKeyConstraint(
            "isin", "venue", "trade_date", "as_of_date", name=op.f("pk_delivery_daily")
        ),
    )

    op.execute(
        "select create_hypertable("
        "'delivery_daily',"
        " by_range('trade_date'::name, interval '1 year'),"
        " create_default_indexes => false"
        ")"
    )
    op.create_index(op.f("ix_delivery_daily_trade_date"), "delivery_daily", ["trade_date"])
    op.execute(
        f"create trigger {TRIGGER} before update on delivery_daily"
        f" for each row execute function reject_fact_update('delivery_daily')"
    )


def downgrade() -> None:
    op.execute(f"drop trigger {TRIGGER} on delivery_daily")
    op.drop_index(op.f("ix_delivery_daily_trade_date"), table_name="delivery_daily")
    op.drop_table("delivery_daily")
    op.add_column("price_daily", sa.Column("delivery_quantity", sa.BigInteger()))
