"""conventional foreign key names

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, name the baseline gave it, name the naming convention produces)
RENAMES = (
    ("listing", "fk_listing_isin_instrument_master", "fk_listing_isin"),
    (
        "listing_suspension",
        "fk_listing_suspension_listing_id_listing",
        "fk_listing_suspension_listing_id",
    ),
    (
        "instrument_primary_venue",
        "fk_instrument_primary_venue_isin_instrument_master",
        "fk_instrument_primary_venue_isin",
    ),
)


def upgrade() -> None:
    for table, baseline_name, conventional_name in RENAMES:
        op.execute(f"alter table {table} rename constraint {baseline_name} to {conventional_name}")


def downgrade() -> None:
    for table, baseline_name, conventional_name in RENAMES:
        op.execute(f"alter table {table} rename constraint {conventional_name} to {baseline_name}")
