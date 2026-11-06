"""screener views

A person's screens of the daily features, each kept under a name. Row security, forced, shows the
API's role a person's own views alone. The role adds and changes views, and removes one by marking
it removed, deleting nothing. A name is unique among the views a person keeps, whatever its case.

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
OWN = "owner_id = (select nullif(current_setting('app.user_id', true), '')::bigint)"
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "screener_view",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "name = btrim(name) and length(name) between 1 and 80",
            name=op.f("ck_screener_view_name"),
        ),
        sa.CheckConstraint("length(query) <= 2000", name=op.f("ck_screener_view_query")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["app_user.id"], name=op.f("fk_screener_view_owner_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screener_view")),
    )
    op.create_index(op.f("ix_screener_view_owner_id"), "screener_view", ["owner_id"])
    op.execute(
        "create unique index uq_screener_view_kept_name on screener_view (owner_id, lower(name))"
        " where removed_at is null"
    )
    op.execute("alter table screener_view enable row level security")
    op.execute("alter table screener_view force row level security")
    op.execute(f"create policy own_only on screener_view for all using ({OWN}) with check ({OWN})")
    op.execute(
        "grant select, insert (owner_id, name, query),"
        f" update (name, query, updated_at, removed_at) on screener_view to {ROLE}"
    )


def downgrade() -> None:
    op.drop_table("screener_view")
