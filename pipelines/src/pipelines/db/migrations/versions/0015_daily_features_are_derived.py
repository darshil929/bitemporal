"""daily features are derived

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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


def upgrade() -> None:
    op.create_table(
        "mart_daily_features",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("primary_venue", sa.String(length=12), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=False),
        *(sa.Column(name, sa.Double(), nullable=True) for name in FIGURES),
        sa.Column("is_52w_high", sa.Boolean(), nullable=True),
        sa.Column("is_52w_low", sa.Boolean(), nullable=True),
        *(sa.Column(name, sa.Double(), nullable=True) for name in LEVELS),
        sa.Column("venue_spread_bps", sa.Double(), nullable=True),
        sa.Column("is_day_complete", sa.Boolean(), nullable=False),
        sa.Column("is_diverging", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "primary_venue in ('BSE', 'NSE')", name=op.f("ck_mart_daily_features_primary_venue")
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_mart_daily_features_isin")
        ),
        sa.PrimaryKeyConstraint("isin", "trade_date", name=op.f("pk_mart_daily_features")),
    )

    op.execute(
        "select create_hypertable("
        "'mart_daily_features',"
        " by_range('trade_date'::name, interval '1 year'),"
        " create_default_indexes => false"
        ")"
    )
    op.create_index(
        op.f("ix_mart_daily_features_trade_date"), "mart_daily_features", ["trade_date"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mart_daily_features_trade_date"), table_name="mart_daily_features")
    op.drop_table("mart_daily_features")
