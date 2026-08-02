"""instrument identity

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_master",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("instrument_type", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'", name=op.f("ck_instrument_master_isin_format")
        ),
        sa.CheckConstraint(
            "country ~ '^[A-Z]{2}$'", name=op.f("ck_instrument_master_country_format")
        ),
        sa.CheckConstraint(
            "instrument_type in ('equity', 'preference_share', 'debt', 'etf', 'warrant', 'right')",
            name=op.f("ck_instrument_master_instrument_type"),
        ),
        sa.PrimaryKeyConstraint("isin", name=op.f("pk_instrument_master")),
    )

    op.create_table(
        "listing",
        sa.Column("listing_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("exchange", sa.String(length=12), nullable=False),
        sa.Column("local_symbol", sa.Text(), nullable=False),
        sa.Column("scrip_code", sa.Text(), nullable=True),
        sa.Column("listing_date", sa.Date(), nullable=False),
        sa.Column("delisting_date", sa.Date(), nullable=True),
        sa.Column("closure_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "exchange ~ '^[A-Z][A-Z0-9]{1,11}$'", name=op.f("ck_listing_exchange_format")
        ),
        sa.CheckConstraint(
            "delisting_date is null or delisting_date >= listing_date",
            name=op.f("ck_listing_closes_after_it_opens"),
        ),
        sa.CheckConstraint(
            "(delisting_date is null) = (closure_reason is null)",
            name=op.f("ck_listing_closure_reason_accompanies_delisting_date"),
        ),
        sa.CheckConstraint(
            "closure_reason is null or closure_reason in ('delisted', 'renamed', 'merged')",
            name=op.f("ck_listing_closure_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_listing_isin_instrument_master")
        ),
        sa.PrimaryKeyConstraint("listing_id", name=op.f("pk_listing")),
        sa.UniqueConstraint(
            "isin",
            "exchange",
            "local_symbol",
            "listing_date",
            name=op.f("uq_listing_isin_exchange_local_symbol_listing_date"),
        ),
    )

    op.create_table(
        "listing_suspension",
        sa.Column("listing_id", sa.BigInteger(), nullable=False),
        sa.Column("suspended_from", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("suspended_to", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "suspended_to is null or suspended_to >= suspended_from",
            name=op.f("ck_listing_suspension_ends_after_it_starts"),
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listing.listing_id"],
            name=op.f("fk_listing_suspension_listing_id_listing"),
        ),
        sa.PrimaryKeyConstraint(
            "listing_id", "suspended_from", "as_of_date", name=op.f("pk_listing_suspension")
        ),
    )

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
            ["isin"],
            ["instrument_master.isin"],
            name=op.f("fk_instrument_primary_venue_isin_instrument_master"),
        ),
        sa.PrimaryKeyConstraint(
            "isin", "effective_from", "as_of_date", name=op.f("pk_instrument_primary_venue")
        ),
    )


def downgrade() -> None:
    op.drop_table("instrument_primary_venue")
    op.drop_table("listing_suspension")
    op.drop_table("listing")
    op.drop_table("instrument_master")
