"""daily features are published

The daily features live in two tables and are read through the view mart_daily_features, which
reads the table holding the published computation; a computation is written into the other table.
Each publish is recorded in feature_release. The stored rows become the first table and its first
release. The downgrade keeps the published table under the view's name and drops the other.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEW = "mart_daily_features"
FIRST = "daily_features_a"
SECOND = "daily_features_b"

FIGURES = (
    "change_1d",
    "return_1d",
    "return_1w",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_1y",
    "momentum_12_1",
    "volatility_20d",
    "rsi_14",
    "adtv_20d",
    "volume_ratio_20d",
    "delivery_pct_1d",
    "delivery_pct_20d",
    "from_52w_high",
)
LEVELS = (
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_20",
    "ema_50",
    "bollinger_20_upper",
    "bollinger_20_lower",
)

# The view reads one table; its rule depends on that table alone among the two.
PUBLISHED = f"""
select distinct dependency.relname
from pg_rewrite as rule
inner join pg_depend as link on link.objid = rule.oid
inner join pg_class as dependency on dependency.oid = link.refobjid
where rule.ev_class = '{VIEW}'::regclass and dependency.relname in ('{FIRST}', '{SECOND}')
"""


def _rename(table: str, to: str) -> None:
    op.rename_table(table, to)
    for kind, suffix in (("pk", ""), ("fk", "_isin"), ("ck", "_primary_venue")):
        op.execute(
            f"alter table {to} rename constraint {kind}_{table}{suffix} to {kind}_{to}{suffix}"
        )
    op.execute(f"alter index ix_{table}_trade_date rename to ix_{to}_trade_date")


def _create_features_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("primary_venue", sa.String(length=12), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=False),
        *(sa.Column(column, sa.Double(), nullable=True) for column in FIGURES),
        sa.Column("is_52w_high", sa.Boolean(), nullable=True),
        sa.Column("is_52w_low", sa.Boolean(), nullable=True),
        *(sa.Column(column, sa.Double(), nullable=True) for column in LEVELS),
        sa.Column("venue_spread_bps", sa.Double(), nullable=True),
        sa.Column("is_day_complete", sa.Boolean(), nullable=False),
        sa.Column("is_diverging", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "primary_venue in ('BSE', 'NSE')", name=op.f(f"ck_{name}_primary_venue")
        ),
        sa.ForeignKeyConstraint(["isin"], ["instrument_master.isin"], name=op.f(f"fk_{name}_isin")),
        sa.PrimaryKeyConstraint("isin", "trade_date", name=op.f(f"pk_{name}")),
    )
    op.execute(
        f"select create_hypertable('{name}', by_range('trade_date'::name, interval '1 year'),"
        " create_default_indexes => false)"
    )
    op.create_index(op.f(f"ix_{name}_trade_date"), name, ["trade_date"])


def upgrade() -> None:
    _rename(VIEW, FIRST)
    _create_features_table(SECOND)
    op.execute(f"create view {VIEW} as select * from {FIRST}")

    op.create_table(
        "feature_release",
        sa.Column("release_id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            f"table_name in ('{FIRST}', '{SECOND}')", name=op.f("ck_feature_release_table_name")
        ),
        sa.CheckConstraint("row_count >= 0", name=op.f("ck_feature_release_row_count")),
        sa.PrimaryKeyConstraint("release_id", name=op.f("pk_feature_release")),
    )
    op.execute(
        "create trigger feature_release_is_append_only before update on feature_release"
        " for each row execute function reject_fact_update('feature_release')"
    )
    op.execute(
        f"insert into feature_release (table_name, trade_date, row_count)"
        f" select '{FIRST}', max(trade_date), count(*) from {FIRST} having count(*) > 0"
    )


def downgrade() -> None:
    published = op.get_bind().execute(sa.text(PUBLISHED)).scalar_one()
    op.execute(f"drop view {VIEW}")
    op.drop_table("feature_release")
    op.drop_table(SECOND if published == FIRST else FIRST)
    _rename(published, VIEW)
