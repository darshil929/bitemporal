"""flow runs

What each run of the history bootstrap or the daily sync did, recorded once it finishes: its days,
start and end, outcome, counts per source, checks and what failed; and each step it ran. The outcome
is the launcher's verdict on the run's report, which fails a run with a failed day that Dagster
counts a success. Rows are written once and never changed. A step is keyed by its run's Dagster id
alone, so steps can be recorded before the run they belong to. The API's role reads both.

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
RUNS = "flow_run"
STEPS = "flow_run_step"
FLOWS = ("bootstrap", "sync")
RUN_OUTCOMES = ("succeeded", "failed", "cancelled")
STEP_OUTCOMES = ("succeeded", "failed", "skipped")
LISTS = ("failures", "warned_checks", "failed_checks", "failed_steps", "unmaterialized")


def _list(name: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
    )


def _append_only(table: str) -> None:
    op.execute(
        f"create trigger {table}_is_append_only before update on {table}"
        f" for each row execute function reject_fact_update('{table}')"
    )


def upgrade() -> None:
    op.create_table(
        RUNS,
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("flow", sa.Text(), nullable=False),
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column(
            "counts", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("checks_passed", sa.Integer(), nullable=False),
        *(_list(name) for name in LISTS),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"flow in {FLOWS}", name=op.f(f"ck_{RUNS}_flow")),
        sa.CheckConstraint(f"outcome in {RUN_OUTCOMES}", name=op.f(f"ck_{RUNS}_outcome")),
        sa.CheckConstraint("last_day >= first_day", name=op.f(f"ck_{RUNS}_days")),
        sa.CheckConstraint("ended_at >= started_at", name=op.f(f"ck_{RUNS}_ended_after")),
        sa.CheckConstraint("checks_passed >= 0", name=op.f(f"ck_{RUNS}_checks_passed")),
        sa.CheckConstraint(
            "jsonb_typeof(counts) = 'object' and "
            + " and ".join(f"jsonb_typeof({name}) = 'array'" for name in LISTS),
            name=op.f(f"ck_{RUNS}_shapes"),
        ),
        sa.CheckConstraint(
            "outcome <> 'succeeded' or "
            + " and ".join(f"{name} = '[]'::jsonb" for name in LISTS if name != "warned_checks"),
            name=op.f(f"ck_{RUNS}_success_failed_nothing"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f(f"pk_{RUNS}")),
    )
    op.create_index(op.f(f"ix_{RUNS}_started_at"), RUNS, ["started_at"])
    op.create_table(
        STEPS,
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.CheckConstraint(f"outcome in {STEP_OUTCOMES}", name=op.f(f"ck_{STEPS}_outcome")),
        sa.CheckConstraint(
            "(outcome = 'skipped') = (started_at is null)", name=op.f(f"ck_{STEPS}_started")
        ),
        sa.CheckConstraint("ended_at >= started_at", name=op.f(f"ck_{STEPS}_ended_after")),
        sa.PrimaryKeyConstraint("run_id", "step", name=op.f(f"pk_{STEPS}")),
    )
    for table in (RUNS, STEPS):
        _append_only(table)
        op.execute(f"grant select on {table} to {ROLE}")


def downgrade() -> None:
    for table in (STEPS, RUNS):
        op.execute(f"drop trigger {table}_is_append_only on {table}")
        op.drop_table(table)
