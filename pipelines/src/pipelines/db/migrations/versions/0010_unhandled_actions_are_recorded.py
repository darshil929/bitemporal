"""unhandled actions are recorded

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPE_CONSTRAINT = "ck_corporate_action_action_type"
TERMS_CONSTRAINT = "ck_corporate_action_terms_match_the_action_type"
RATIO_CONSTRAINT = "ck_corporate_action_everything_else_changes_a_ratio"
TEXT_CONSTRAINT = "ck_corporate_action_an_unhandled_action_keeps_its_text"

WITH_UNHANDLED = (
    "action_type in ('split', 'bonus', 'consolidation', 'rights', 'dividend', 'unhandled')"
)
WITHOUT_UNHANDLED = "action_type in ('split', 'bonus', 'consolidation', 'rights', 'dividend')"

TERMS_WITH_UNHANDLED = "(action_type not in ('dividend', 'unhandled')) = (ratio_from is not null)"
TERMS_WITHOUT_UNHANDLED = "(action_type <> 'dividend') = (ratio_from is not null)"

KEEPS_ITS_TEXT = "action_type <> 'unhandled' or purpose is not null"


def upgrade() -> None:
    op.add_column("corporate_action", sa.Column("purpose", sa.Text(), nullable=True))

    op.drop_constraint(op.f(TYPE_CONSTRAINT), "corporate_action", type_="check")
    op.create_check_constraint(op.f(TYPE_CONSTRAINT), "corporate_action", WITH_UNHANDLED)

    op.drop_constraint(op.f(RATIO_CONSTRAINT), "corporate_action", type_="check")
    op.create_check_constraint(op.f(TERMS_CONSTRAINT), "corporate_action", TERMS_WITH_UNHANDLED)

    op.create_check_constraint(op.f(TEXT_CONSTRAINT), "corporate_action", KEEPS_ITS_TEXT)


def downgrade() -> None:
    # The earlier constraints admit no unhandled action, so the rows recording one go with them.
    op.execute("delete from corporate_action where action_type = 'unhandled'")

    op.drop_constraint(op.f(TEXT_CONSTRAINT), "corporate_action", type_="check")

    op.drop_constraint(op.f(TERMS_CONSTRAINT), "corporate_action", type_="check")
    op.create_check_constraint(op.f(RATIO_CONSTRAINT), "corporate_action", TERMS_WITHOUT_UNHANDLED)

    op.drop_constraint(op.f(TYPE_CONSTRAINT), "corporate_action", type_="check")
    op.create_check_constraint(op.f(TYPE_CONSTRAINT), "corporate_action", WITHOUT_UNHANDLED)

    op.drop_column("corporate_action", "purpose")
