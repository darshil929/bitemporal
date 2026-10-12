"""the api reads as a role of its own

The API connects as bitemporal_api, a role that bypasses no row security, owns nothing and reads
what the application shows. A role belongs to the whole cluster while each environment is a schema,
so it is created only where absent and with no password, which an operator sets, and a downgrade
removes this schema's grants and keeps the role. dbt grants the role the marts it builds.

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"

# What the API reads outside the marts dbt builds: the published features, their releases and the
# migration the schema is at.
READ = ("mart_daily_features", "feature_release", "alembic_version")


def _on_schema(statement: str) -> None:
    op.execute(f"do $$ begin execute format('{statement}', current_schema()); end $$")


def upgrade() -> None:
    op.execute(
        f"""
        do $$
        begin
            if not exists (select from pg_roles where rolname = '{ROLE}') then
                create role {ROLE} login nosuperuser nocreatedb nocreaterole nobypassrls;
            end if;
        end
        $$
        """
    )
    _on_schema(f"grant usage on schema %I to {ROLE}")
    op.execute(f"grant select on {', '.join(READ)} to {ROLE}")


def downgrade() -> None:
    op.execute(f"revoke select on {', '.join(READ)} from {ROLE}")
    _on_schema(f"revoke usage on schema %I from {ROLE}")
