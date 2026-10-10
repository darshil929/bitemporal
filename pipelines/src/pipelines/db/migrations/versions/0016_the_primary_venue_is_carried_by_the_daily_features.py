"""the primary venue is carried by the daily features

Each daily feature row names the venue its figures are read from, designated with them from the
bars. The downgrade recreates the table of designated stretches empty; its rows are not restored.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("instrument_primary_venue")


def downgrade() -> None:
    op.create_table(
        "instrument_primary_venue",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("venue", sa.String(length=12), nullable=False),
        sa.CheckConstraint(
            "venue ~ '^[A-Z][A-Z0-9]{1,11}$'",
            name=op.f("ck_instrument_primary_venue_venue_format"),
        ),
        sa.CheckConstraint(
            "effective_to is null or effective_to > effective_from",
            name=op.f("ck_instrument_primary_venue_ends_after_it_starts"),
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_instrument_primary_venue_isin")
        ),
        sa.PrimaryKeyConstraint(
            "isin", "effective_from", "as_of_date", name=op.f("pk_instrument_primary_venue")
        ),
    )
