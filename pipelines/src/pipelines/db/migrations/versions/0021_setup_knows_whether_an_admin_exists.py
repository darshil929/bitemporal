"""setup knows whether an admin exists

The application offers its first-run setup only while no admin exists. No one is signed in to ask,
and row security shows the API's role no account without one, so a function owned by the schema's
owner answers.

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
FUNCTION = "an_admin_exists()"
BODY = """
    returns boolean language sql stable security definer set search_path = {schema}, pg_temp as $$
        select exists (select 1 from app_user where role = 'admin')
    $$"""


def upgrade() -> None:
    schema = op.get_bind().execute(sa.text("select current_schema()")).scalar_one()
    op.execute(f"create function {FUNCTION} {BODY.format(schema=schema)}")
    op.execute(f"revoke all on function {FUNCTION} from public")
    op.execute(f"grant execute on function {FUNCTION} to {ROLE}")


def downgrade() -> None:
    op.execute(f"drop function {FUNCTION}")
