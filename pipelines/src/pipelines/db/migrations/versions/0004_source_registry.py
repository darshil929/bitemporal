"""source registry

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_registry",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("requests_per_second", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("cache_policy", sa.Text(), nullable=False),
        sa.Column("sebi_curation_ref", sa.Text(), nullable=True),
        sa.Column("owner_notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "requests_per_second > 0", name=op.f("ck_source_registry_rate_is_positive")
        ),
        sa.CheckConstraint("tier between 1 and 4", name=op.f("ck_source_registry_tier_range")),
        sa.PrimaryKeyConstraint("source_id", name=op.f("pk_source_registry")),
    )
    op.create_table(
        "source_schema_version",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "effective_to is null or effective_to >= effective_from",
            name=op.f("ck_source_schema_version_ends_after_it_starts"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_registry.source_id"],
            name=op.f("fk_source_schema_version_source_id"),
        ),
        sa.PrimaryKeyConstraint(
            "source_id", "effective_from", name=op.f("pk_source_schema_version")
        ),
    )


def downgrade() -> None:
    op.drop_table("source_schema_version")
    op.drop_table("source_registry")
