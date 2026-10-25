"""instrument face values

The face value each exchange's list of securities gives an instrument, written when a list first
gives it or changes it. A split or consolidation changes the face value under a new ISIN.

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER = "instrument_face_value_is_append_only"


def upgrade() -> None:
    op.create_table(
        "instrument_face_value",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("face_value", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.CheckConstraint(
            "face_value > 0", name=op.f("ck_instrument_face_value_face_value_is_positive")
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_instrument_face_value_isin")
        ),
        sa.PrimaryKeyConstraint(
            "isin", "source_id", "as_of_date", name=op.f("pk_instrument_face_value")
        ),
    )
    op.execute(
        f"create trigger {TRIGGER} before update on instrument_face_value"
        f" for each row execute function reject_fact_update('instrument_face_value')"
    )


def downgrade() -> None:
    op.execute(f"drop trigger {TRIGGER} on instrument_face_value")
    op.drop_table("instrument_face_value")
