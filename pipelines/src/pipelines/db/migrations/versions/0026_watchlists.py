"""watchlists

A person's lists of instruments, each entry following one venue, and one alert at a time on an
entry. Row security, forced on each table, shows the API's role a person's own rows alone, and an
entry or alert belongs to a list or entry of the same person. The role deletes nothing: a list is
marked removed, and an entry or alert ends, a changed venue or rule starting a new one. A list's
name is unique among the lists a person keeps, whatever its case; an instrument is kept once in a
list, and an entry has one alert open. Each of these keys leads with the owner, since a unique index
is checked past row security, before the key holding a row to its owner's list or entry.

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
TABLES = ("watchlist", "watchlist_entry", "watchlist_alert")
OWN = "owner_id = (select nullif(current_setting('app.user_id', true), '')::bigint)"
NOW = sa.text("now()")
RULES = (
    "move_beyond",
    "close_above",
    "close_below",
    "delivery_above",
    "delivery_below",
    "spread_above",
)

GRANTS = {
    "watchlist": "insert (owner_id, name), update (name, updated_at, removed_at)",
    "watchlist_entry": "insert (owner_id, watchlist_id, isin, venue), update (ended_at)",
    "watchlist_alert": "insert (owner_id, entry_id, rule, threshold), update (ended_at)",
}


def _create_lists() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "name = btrim(name) and length(name) between 1 and 80", name=op.f("ck_watchlist_name")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"], name=op.f("fk_watchlist_owner_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_watchlist_id_owner_id")),
    )
    op.execute(
        "create unique index uq_watchlist_kept_name on watchlist (owner_id, lower(name))"
        " where removed_at is null"
    )


def _create_entries() -> None:
    op.create_table(
        "watchlist_entry",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("watchlist_id", sa.BigInteger(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("venue", sa.String(length=12), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "venue ~ '^[A-Z][A-Z0-9]{1,11}$'", name=op.f("ck_watchlist_entry_venue_format")
        ),
        sa.CheckConstraint(
            "ended_at is null or ended_at >= added_at", name=op.f("ck_watchlist_entry_ends_after")
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_watchlist_entry_isin")
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id", "owner_id"],
            ["watchlist.id", "watchlist.owner_id"],
            name=op.f("fk_watchlist_entry_watchlist_id_owner_id"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["app_user.id"], name=op.f("fk_watchlist_entry_owner_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_entry")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("uq_watchlist_entry_id_owner_id")),
    )
    op.execute(
        "create unique index uq_watchlist_entry_kept_isin"
        " on watchlist_entry (owner_id, watchlist_id, isin) where ended_at is null"
    )


def _create_alerts() -> None:
    op.create_table(
        "watchlist_alert",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"rule in {RULES}", name=op.f("ck_watchlist_alert_rule")),
        sa.CheckConstraint(
            "threshold > 0 and (rule not like 'delivery%' or threshold < 100)",
            name=op.f("ck_watchlist_alert_threshold"),
        ),
        sa.CheckConstraint(
            "ended_at is null or ended_at >= created_at",
            name=op.f("ck_watchlist_alert_ends_after"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "owner_id"],
            ["watchlist_entry.id", "watchlist_entry.owner_id"],
            name=op.f("fk_watchlist_alert_entry_id_owner_id"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["app_user.id"], name=op.f("fk_watchlist_alert_owner_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_alert")),
    )
    op.execute(
        "create unique index uq_watchlist_alert_open on watchlist_alert (owner_id, entry_id)"
        " where ended_at is null"
    )


def upgrade() -> None:
    _create_lists()
    _create_entries()
    _create_alerts()
    for table in TABLES:
        op.create_index(op.f(f"ix_{table}_owner_id"), table, ["owner_id"])
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(f"create policy own_only on {table} for all using ({OWN}) with check ({OWN})")
        op.execute(f"grant select, {GRANTS[table]} on {table} to {ROLE}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
