"""flow request cancels

An admin may ask for a request to be cancelled: the API's role sets the time a cancel was asked for,
under a policy wanting an admin, and the flows act on it. A request cancelled before it started
takes the status cancelled. A request names the run carrying it now or last. The fetch log is read
by when each attempt was made.

Revision ID: 0030
Revises: 0029
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "bitemporal_api"
TABLE = "flow_request"
IS_ADMIN = "(select app_user_is_admin())"
STATUS = f"ck_{TABLE}_status"
STATUSES = ("requested", "started", "refused", "finished")


def _statuses(statuses: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(STATUS), TABLE, type_="check")
    op.create_check_constraint(op.f(STATUS), TABLE, f"status in {statuses}")


def upgrade() -> None:
    _statuses((*STATUSES, "cancelled"))
    op.execute(f"alter table {TABLE} add column run_id text")
    op.execute(
        f"create policy admin_cancels on {TABLE} for update using ({IS_ADMIN}) with check ({IS_ADMIN})"
    )
    op.execute(f"grant update (cancel_requested_at) on {TABLE} to {ROLE}")
    op.create_index(op.f("ix_ingestion_log_fetched_at"), "ingestion_log", ["fetched_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_log_fetched_at"), "ingestion_log")
    op.execute(f"revoke update (cancel_requested_at) on {TABLE} from {ROLE}")
    op.execute(f"drop policy admin_cancels on {TABLE}")
    op.execute(f"alter table {TABLE} drop column run_id")
    op.execute(f"delete from {TABLE} where status = 'cancelled'")
    _statuses(STATUSES)
