"""close outside traded range

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_price_daily_bar_is_internally_consistent"

BOUNDED_BY_TRADES = "high >= low and high >= open and low <= open"
BOUNDED_INCLUDING_CLOSE = (
    "high >= low and high >= open and high >= close and low <= open and low <= close"
)


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "price_daily", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "price_daily", BOUNDED_BY_TRADES)


def downgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "price_daily", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "price_daily", BOUNDED_INCLUDING_CLOSE)
