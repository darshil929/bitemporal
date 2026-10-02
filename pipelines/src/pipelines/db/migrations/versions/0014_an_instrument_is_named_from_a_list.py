"""an instrument is named from a list

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER = "instrument_name_is_append_only"


def upgrade() -> None:
    op.create_table(
        "instrument_name",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("name <> ''", name=op.f("ck_instrument_name_name_is_not_empty")),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_instrument_name_isin")
        ),
        sa.PrimaryKeyConstraint("isin", "source_id", "as_of_date", name=op.f("pk_instrument_name")),
    )
    op.execute(
        f"create trigger {TRIGGER} before update on instrument_name"
        f" for each row execute function reject_fact_update('instrument_name')"
    )


def downgrade() -> None:
    op.execute(f"drop trigger {TRIGGER} on instrument_name")
    op.drop_table("instrument_name")
