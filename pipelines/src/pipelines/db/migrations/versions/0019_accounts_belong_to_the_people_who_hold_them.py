"""accounts belong to the people who hold them

People sign in with accounts the application holds. Row security, forced on both tables here, lets
the API's role see a person's own rows and, for an admin, every account; the user is the
transaction's app.user_id. Before anyone is signed in, functions owned by the schema's owner answer
the questions sign-in asks. The API's role reads no password hash and deletes nothing.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
TABLES = ("app_user", "user_setting")
SIGNED_IN = "(select nullif(current_setting('app.user_id', true), '')::bigint)"
IS_ADMIN = "(select app_user_is_admin())"
NOW = sa.text("now()")

# Each policy: table, name, command, the rows it reaches, the rows it may leave.
POLICIES = (
    ("app_user", "own_or_admin_reads", "select", f"id = {SIGNED_IN} or {IS_ADMIN}", None),
    ("app_user", "admin_adds", "insert", None, IS_ADMIN),
    ("app_user", "own_or_admin_changes", "update", f"id = {SIGNED_IN} or {IS_ADMIN}", None),
    ("user_setting", "own_only", "all", f"owner_id = {SIGNED_IN}", f"owner_id = {SIGNED_IN}"),
)

# The functions run as their owner, whom row security does not bind, and answer one question each.
FUNCTIONS = {
    "app_user_is_admin()": """
        returns boolean language sql stable as $$
            select exists (
                select 1 from app_user
                where id = nullif(current_setting('app.user_id', true), '')::bigint
                    and role = 'admin' and disabled_at is null
            )
        $$""",
    "sign_in_candidate(candidate text)": """
        returns table (
            id bigint, password_hash text, role text, must_change_password boolean,
            temporary_password_expires_at timestamptz, failed_sign_ins integer,
            sign_in_paused_until timestamptz, disabled_at timestamptz
        ) language sql stable as $$
            select id, password_hash, role, must_change_password, temporary_password_expires_at,
                failed_sign_ins, sign_in_paused_until, disabled_at
            from app_user where username = lower(candidate)
        $$""",
    "record_failed_sign_in(account bigint, paused_until timestamptz)": """
        returns integer language sql volatile as $$
            update app_user
            set failed_sign_ins = failed_sign_ins + 1,
                sign_in_paused_until = coalesce(paused_until, sign_in_paused_until)
            where id = account
            returning failed_sign_ins
        $$""",
    "create_first_admin(admin_username text, admin_display_name text, admin_password_hash text)": """
        returns bigint language plpgsql volatile as $$
        declare
            created bigint;
        begin
            lock table app_user in share row exclusive mode;
            if exists (select 1 from app_user where role = 'admin') then
                raise exception 'an admin exists already';
            end if;
            insert into app_user (username, display_name, role, password_hash)
            values (lower(admin_username), admin_display_name, 'admin', admin_password_hash)
            returning id into created;
            return created;
        end
        $$""",
}

# The API's role changes a role, a username or whether an account is enabled only as an admin,
# and never leaves the installation without an enabled admin.
GUARD = f"""
create function app_user_guard() returns trigger language plpgsql as $$
begin
    if current_user <> '{ROLE}' then
        return new;
    end if;
    if (new.role, new.username, new.disabled_at)
            is distinct from (old.role, old.username, old.disabled_at)
        and not app_user_is_admin() then
        raise exception 'only an admin changes a role, a username or an account''s state'
            using errcode = 'insufficient_privilege';
    end if;
    if old.role = 'admin' and old.disabled_at is null
        and (new.role <> 'admin' or new.disabled_at is not null)
        and not exists (
            select 1 from app_user
            where role = 'admin' and disabled_at is null and id <> old.id
        ) then
        raise exception 'the last enabled admin stays an enabled admin'
            using errcode = 'restrict_violation';
    end if;
    return new;
end
$$
"""

PASSWORD_STATE = ("must_change_password", "temporary_password_expires_at")
SIGN_IN_STATE = ("failed_sign_ins", "sign_in_paused_until", "disabled_at")

# What the API's role may do on each table, column by column where a column is withheld.
GRANTS: dict[str, dict[str, tuple[str, ...]]] = {
    "app_user": {
        "select": (
            "id",
            "username",
            "display_name",
            "role",
            *PASSWORD_STATE,
            *SIGN_IN_STATE,
            "created_at",
        ),
        "insert": ("username", "display_name", "role", "password_hash", *PASSWORD_STATE),
        "update": (
            "username",
            "display_name",
            "role",
            "password_hash",
            *PASSWORD_STATE,
            *SIGN_IN_STATE,
        ),
    },
    "user_setting": {"select": (), "insert": (), "update": ("theme", "updated_at")},
}


def _create_tables() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("temporary_password_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_sign_ins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sign_in_paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "username = lower(username) and length(username) between 3 and 64",
            name=op.f("ck_app_user_username"),
        ),
        sa.CheckConstraint(
            "length(display_name) between 1 and 80", name=op.f("ck_app_user_display_name")
        ),
        sa.CheckConstraint("role in ('admin', 'member')", name=op.f("ck_app_user_role")),
        sa.CheckConstraint("failed_sign_ins >= 0", name=op.f("ck_app_user_failed_sign_ins")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("username", name=op.f("uq_app_user_username")),
    )
    op.create_table(
        "user_setting",
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("theme", sa.Text(), server_default="light", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("theme in ('light', 'dark')", name=op.f("ck_user_setting_theme")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["app_user.id"], name=op.f("fk_user_setting_owner_id")
        ),
        sa.PrimaryKeyConstraint("owner_id", name=op.f("pk_user_setting")),
    )


def upgrade() -> None:
    _create_tables()
    schema = op.get_bind().execute(sa.text("select current_schema()")).scalar_one()
    for signature, body in FUNCTIONS.items():
        owned = f" security definer set search_path = {schema}, pg_temp as $$"
        op.execute(f"create function {signature} {body.strip().replace(' as $$', owned, 1)}")
        op.execute(f"revoke all on function {signature} from public")
        op.execute(f"grant execute on function {signature} to {ROLE}")
    op.execute(GUARD)
    op.execute(
        "create trigger app_user_guard before update on app_user"
        " for each row execute function app_user_guard()"
    )
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
    op.execute("drop function app_user_guard()")
    for signature in FUNCTIONS:
        op.execute(f"drop function {signature.split('(')[0]}")
