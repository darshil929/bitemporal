"""price and action facts

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = ("price_daily", "corporate_action")

# The table name is passed in rather than read from tg_table_name, which on a hypertable
# reports the chunk and tells an operator nothing.
REJECT_UPDATE_FUNCTION = """
create function reject_fact_update() returns trigger
language plpgsql as $$
begin
    raise exception 'fact rows are append-only, table %', tg_argv[0]
        using errcode = 'restrict_violation';
end;
$$
"""


def upgrade() -> None:
    op.create_table(
        "ingestion_log",
        sa.Column("ingestion_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("partition_key", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(outcome = 'succeeded') = (row_count is not null)",
            name=op.f("ck_ingestion_log_a_success_counts_its_rows"),
        ),
        sa.CheckConstraint(
            "outcome in ('succeeded', 'not_published', 'failed')",
            name=op.f("ck_ingestion_log_outcome"),
        ),
        sa.PrimaryKeyConstraint("ingestion_id", name=op.f("pk_ingestion_log")),
    )

    op.create_table(
        "corporate_action",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ratio_from", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("ratio_to", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("dividend_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.CheckConstraint(
            "(action_type <> 'dividend') = (ratio_from is not null)",
            name=op.f("ck_corporate_action_everything_else_changes_a_ratio"),
        ),
        sa.CheckConstraint(
            "(action_type = 'dividend') = (dividend_amount is not null)",
            name=op.f("ck_corporate_action_a_dividend_pays_an_amount"),
        ),
        sa.CheckConstraint(
            "action_type in ('split', 'bonus', 'consolidation', 'rights', 'dividend')",
            name=op.f("ck_corporate_action_action_type"),
        ),
        sa.CheckConstraint(
            "(ratio_from is null or ratio_from > 0) and (ratio_to is null or ratio_to > 0)",
            name=op.f("ck_corporate_action_ratio_sides_are_positive"),
        ),
        sa.CheckConstraint(
            "(ratio_from is null) = (ratio_to is null)",
            name=op.f("ck_corporate_action_ratio_has_both_sides"),
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_corporate_action_isin")
        ),
        sa.PrimaryKeyConstraint(
            "isin",
            "action_type",
            "ex_date",
            "source_id",
            "as_of_date",
            name=op.f("pk_corporate_action"),
        ),
    )

    op.create_table(
        "price_daily",
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("venue", sa.String(length=12), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("previous_close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("turnover", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("trade_count", sa.BigInteger(), nullable=True),
        sa.Column("delivery_quantity", sa.BigInteger(), nullable=True),
        sa.Column("adjusted_open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("adjusted_high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("adjusted_low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("adjusted_close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.CheckConstraint(
            "venue ~ '^[A-Z][A-Z0-9]{1,11}$'", name=op.f("ck_price_daily_venue_format")
        ),
        sa.CheckConstraint(
            "(adjusted_open is null) = (adjusted_close is null)"
            " and (adjusted_high is null) = (adjusted_close is null)"
            " and (adjusted_low is null) = (adjusted_close is null)",
            name=op.f("ck_price_daily_adjusted_prices_arrive_together"),
        ),
        sa.CheckConstraint(
            "delivery_quantity is null or delivery_quantity <= volume",
            name=op.f("ck_price_daily_delivery_is_part_of_volume"),
        ),
        sa.CheckConstraint(
            "high >= low and high >= open and high >= close and low <= open and low <= close",
            name=op.f("ck_price_daily_bar_is_internally_consistent"),
        ),
        sa.CheckConstraint(
            "open >= 0 and high >= 0 and low >= 0 and close >= 0 and volume >= 0",
            name=op.f("ck_price_daily_quantities_are_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["isin"], ["instrument_master.isin"], name=op.f("fk_price_daily_isin")
        ),
        sa.PrimaryKeyConstraint(
            "isin", "venue", "trade_date", "as_of_date", name=op.f("pk_price_daily")
        ),
    )

    # A year of daily bars per chunk. Default indexes are suppressed so the one index this table
    # needs is declared alongside the model and stays visible to autogenerate.
    op.execute(
        "select create_hypertable("
        "'price_daily',"
        " by_range('trade_date'::name, interval '1 year'),"
        " create_default_indexes => false"
        ")"
    )
    op.create_index(op.f("ix_price_daily_trade_date"), "price_daily", ["trade_date"])

    op.execute(REJECT_UPDATE_FUNCTION)
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"create trigger {table}_is_append_only before update on {table}"
            f" for each row execute function reject_fact_update('{table}')"
        )


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        op.execute(f"drop trigger {table}_is_append_only on {table}")
    op.execute("drop function reject_fact_update()")

    op.drop_index(op.f("ix_price_daily_trade_date"), table_name="price_daily")
    op.drop_table("price_daily")
    op.drop_table("corporate_action")
    op.drop_table("ingestion_log")
