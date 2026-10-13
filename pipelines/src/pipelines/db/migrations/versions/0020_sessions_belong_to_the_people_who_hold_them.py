"""sessions belong to the people who hold them

A session is a person's sign-in on one device, kept once it ends. Row security, forced, lets the
API's role see a person's own sessions, and an admin end anyone's; the cookie's token is found
through a function owned by the schema's owner, since no one is signed in when it is read. The
session limits are one row everyone reads and an admin changes. The API's role reads no token hash
and deletes nothing.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
TABLES = ("app_session", "app_setting")
SIGNED_IN = "(select nullif(current_setting('app.user_id', true), '')::bigint)"
IS_ADMIN = "(select app_user_is_admin())"
NOW = sa.text("now()")

# Each policy: table, name, command, the rows it reaches, the rows it may leave.
POLICIES = (
    ("app_session", "own_or_admin_reads", "select", f"owner_id = {SIGNED_IN} or {IS_ADMIN}", None),
    ("app_session", "own_starts", "insert", None, f"owner_id = {SIGNED_IN}"),
    ("app_session", "own_or_admin_ends", "update", f"owner_id = {SIGNED_IN} or {IS_ADMIN}", None),
    ("app_setting", "everyone_reads", "select", "true", None),
    ("app_setting", "admin_changes", "update", IS_ADMIN, None),
)

SESSION_FOR_TOKEN = "session_for_token(token bytea)"
SESSION_FOR_TOKEN_BODY = """
    returns table (
        id bigint, owner_id bigint, created_at timestamptz, last_seen_at timestamptz,
        ended_at timestamptz, ended_reason text
    ) language sql stable security definer set search_path = {schema}, pg_temp as $$
        select id, owner_id, created_at, last_seen_at, ended_at, ended_reason
        from app_session where token_hash = token
    $$"""

# What the API's role may do on each table, column by column where a column is withheld.
GRANTS: dict[str, dict[str, tuple[str, ...]]] = {
    "app_session": {
        "select": (
            "id",
            "owner_id",
            "created_at",
            "last_seen_at",
            "ended_at",
            "ended_reason",
            "user_agent_summary",
        ),
        "insert": ("owner_id", "token_hash", "user_agent_summary"),
        "update": ("last_seen_at", "ended_at", "ended_reason"),
    },
    "app_setting": {
        "select": (),
        "update": ("session_idle_minutes", "session_max_hours", "updated_at"),
    },
}


def _create_tables() -> None:
    op.create_table(
        "app_session",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", sa.Text(), nullable=True),
        sa.Column("user_agent_summary", sa.Text(), nullable=True),
        sa.CheckConstraint("length(token_hash) = 32", name=op.f("ck_app_session_token_hash")),
        sa.CheckConstraint(
            "ended_reason in ('idle', 'limit', 'signed_out', 'signed_out_elsewhere', 'disabled')",
            name=op.f("ck_app_session_ended_reason"),
        ),
        sa.CheckConstraint(
            "(ended_at is null) = (ended_reason is null)", name=op.f("ck_app_session_ended")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["app_user.id"], name=op.f("fk_app_session_owner_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_app_session_token_hash")),
    )
    op.create_index(op.f("ix_app_session_owner_id"), "app_session", ["owner_id"])
    op.create_table(
        "app_setting",
        sa.Column("id", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("session_idle_minutes", sa.Integer(), server_default="120", nullable=False),
        sa.Column("session_max_hours", sa.Integer(), server_default="12", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_app_setting_one_row")),
        sa.CheckConstraint(
            "session_idle_minutes between 5 and 1440", name=op.f("ck_app_setting_idle_minutes")
        ),
        sa.CheckConstraint(
            "session_max_hours between 1 and 72", name=op.f("ck_app_setting_max_hours")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_setting")),
    )
    op.execute("insert into app_setting default values")


def upgrade() -> None:
    _create_tables()
    schema = op.get_bind().execute(sa.text("select current_schema()")).scalar_one()
    op.execute(
        f"create function {SESSION_FOR_TOKEN} {SESSION_FOR_TOKEN_BODY.format(schema=schema)}"
    )
    op.execute(f"revoke all on function {SESSION_FOR_TOKEN} from public")
    op.execute(f"grant execute on function {SESSION_FOR_TOKEN} to {ROLE}")
    for table in TABLES:
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
    for table, name, command, using, check in POLICIES:
        reach = f" using ({using})" if using else ""
        leave = f" with check ({check})" if check else ""
        op.execute(f"create policy {name} on {table} for {command}{reach}{leave}")
    for table, privileges in GRANTS.items():
        granted = ", ".join(
            f"{command} ({', '.join(columns)})" if columns else command
            for command, columns in privileges.items()
        )
        op.execute(f"grant {granted} on {table} to {ROLE}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("drop function session_for_token")
