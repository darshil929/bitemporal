"""corporate action withdrawal

A corporate action stored as unhandled, the venue's text with no terms read from it, is withdrawn
by a further version of its own when a later answer no longer holds the text and holds other
actions for that instrument and day. Every row stored before reads as not withdrawn.

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "corporate_action"
CONSTRAINT = "ck_corporate_action_a_withdrawal_is_of_an_unhandled_action"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("is_withdrawn", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        op.f(CONSTRAINT), TABLE, "not is_withdrawn or action_type = 'unhandled'"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.drop_column(TABLE, "is_withdrawn")
