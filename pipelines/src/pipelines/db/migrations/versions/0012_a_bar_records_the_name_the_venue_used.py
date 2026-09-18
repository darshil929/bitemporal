"""a bar records the name the venue used

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A stretch covers the day, so the listing in force supplies the name a stored bar was published
# under. A bar outside every stretch has no name to take, and the column below then stays null,
# which the constraint refuses.
BACKFILL = """
update price_daily p
set local_symbol = l.local_symbol, scrip_code = l.scrip_code
from listing l
where l.isin = p.isin
  and l.exchange = p.venue
  and l.listing_date <= p.trade_date
  and (l.delisting_date is null or p.trade_date <= l.delisting_date)
  and p.local_symbol is null
"""


def upgrade() -> None:
    op.add_column("price_daily", sa.Column("local_symbol", sa.Text(), nullable=True))
    op.add_column("price_daily", sa.Column("scrip_code", sa.Text(), nullable=True))

    op.execute(BACKFILL)
    op.alter_column("price_daily", "local_symbol", nullable=False)


def downgrade() -> None:
    op.drop_column("price_daily", "scrip_code")
    op.drop_column("price_daily", "local_symbol")
