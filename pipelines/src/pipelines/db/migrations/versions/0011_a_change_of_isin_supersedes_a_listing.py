"""a change of isin supersedes a listing

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_listing_closure_reason"

WITH_SUPERSEDED = (
    "closure_reason is null or closure_reason in ('delisted', 'renamed', 'merged', 'superseded')"
)
WITHOUT_SUPERSEDED = "closure_reason is null or closure_reason in ('delisted', 'renamed', 'merged')"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "listing", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "listing", WITH_SUPERSEDED)


def downgrade() -> None:
    # The earlier constraint admits no superseded listing, and the stretch did stop trading.
    op.execute("update listing set closure_reason = 'delisted' where closure_reason = 'superseded'")

    op.drop_constraint(op.f(CONSTRAINT), "listing", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "listing", WITHOUT_SUPERSEDED)
