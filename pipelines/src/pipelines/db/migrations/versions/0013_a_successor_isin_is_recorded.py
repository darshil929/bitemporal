"""a successor isin is recorded

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_succession",
        sa.Column("predecessor_isin", sa.String(length=12), nullable=False),
        sa.Column("exchange", sa.String(length=12), nullable=False),
        sa.Column("successor_isin", sa.String(length=12), nullable=False),
        sa.Column("changed_on", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "exchange ~ '^[A-Z][A-Z0-9]{1,11}$'",
            name=op.f("ck_instrument_succession_exchange_format"),
        ),
        sa.CheckConstraint(
            "predecessor_isin <> successor_isin",
            name=op.f("ck_instrument_succession_an_isin_does_not_succeed_itself"),
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_isin"],
            ["instrument_master.isin"],
            name=op.f("fk_instrument_succession_predecessor_isin_instrument_master"),
        ),
        sa.ForeignKeyConstraint(
            ["successor_isin"],
            ["instrument_master.isin"],
            name=op.f("fk_instrument_succession_successor_isin_instrument_master"),
        ),
        sa.PrimaryKeyConstraint(
            "predecessor_isin", "exchange", name=op.f("pk_instrument_succession")
        ),
    )


def downgrade() -> None:
    op.drop_table("instrument_succession")
