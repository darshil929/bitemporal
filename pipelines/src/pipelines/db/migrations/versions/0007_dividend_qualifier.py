"""dividend qualifier

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY = "pk_corporate_action"
DEFAULT_QUALIFIER = "ordinary"
WITHOUT_QUALIFIER = ("isin", "action_type", "ex_date", "source_id", "as_of_date")
WITH_QUALIFIER = (*WITHOUT_QUALIFIER, "qualifier")


def upgrade() -> None:
    op.add_column(
        "corporate_action",
        sa.Column("qualifier", sa.Text(), nullable=False, server_default=DEFAULT_QUALIFIER),
    )
    op.drop_constraint(op.f(KEY), "corporate_action", type_="primary")
    op.create_primary_key(op.f(KEY), "corporate_action", list(WITH_QUALIFIER))


def downgrade() -> None:
    op.drop_constraint(op.f(KEY), "corporate_action", type_="primary")
    op.create_primary_key(op.f(KEY), "corporate_action", list(WITHOUT_QUALIFIER))
    op.drop_column("corporate_action", "qualifier")
