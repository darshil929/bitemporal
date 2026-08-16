"""adjusted prices are derived

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADJUSTED_COLUMNS = ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close")
CONSTRAINT = "ck_price_daily_adjusted_prices_arrive_together"
PAIRING = (
    "(adjusted_open is null) = (adjusted_close is null)"
    " and (adjusted_high is null) = (adjusted_close is null)"
    " and (adjusted_low is null) = (adjusted_close is null)"
)


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "price_daily", type_="check")
    for column in ADJUSTED_COLUMNS:
        op.drop_column("price_daily", column)


def downgrade() -> None:
    for column in ADJUSTED_COLUMNS:
        op.add_column("price_daily", sa.Column(column, sa.Numeric(precision=18, scale=4)))
    op.create_check_constraint(op.f(CONSTRAINT), "price_daily", PAIRING)
