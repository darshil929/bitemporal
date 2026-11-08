"""Watchlist alert verdicts as the flows write them and the API's role reads them."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
from psycopg.errors import (
    CheckViolation,
    ForeignKeyViolation,
    InsufficientPrivilege,
    RestrictViolation,
    UniqueViolation,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.config import ApiSettings
from api.db.database import Database
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

HDFC_BANK = "INE040A01034"
JUDGE = (
    "insert into watchlist_alert_evaluation"
    " (owner_id, alert_id, trade_date, as_of_date, status, figure, paused_reason)"
    " values (%(owner)s, %(alert)s, %(day)s, %(known)s, %(status)s, %(figure)s, %(reason)s)"
)
API_JUDGE = (
    "insert into watchlist_alert_evaluation (owner_id, alert_id, trade_date, as_of_date, status)"
    " values (:owner, :alert, '2025-12-31', '2025-12-31', 'watching')"
)
VERDICTS = text("select status, figure from watchlist_alert_evaluation order by trade_date")


@pytest.fixture
async def database(migrated_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(migrated_settings)
    yield opened
    await opened.close()


@pytest.fixture
def owner(migrated_settings: ApiSettings, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    """The tables' owner, which writes verdicts as the flows do."""
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", autocommit=True
    ) as connection:
        yield connection


@pytest.fixture
def alerts(owner: psycopg.Connection) -> dict[str, int]:
    """Two people, each with an alert on a move beyond 2% for HDFC Bank on NSE, by person."""
    owner.execute(
        "insert into instrument_master (isin, name, country, instrument_type)"
        " values (%s, 'HDFC Bank Ltd', 'IN', 'equity')",
        (HDFC_BANK,),
    )
    found = {}
    for username in ("asha", "ravi"):
        person = one(
            owner,
            "insert into app_user (username, display_name, role, password_hash)"
            " values (%s, %s, 'member', 'unused') returning id",
            (username, username.title()),
        )
        watchlist = one(
            owner,
            "insert into watchlist (owner_id, name) values (%s, 'Watchlist') returning id",
            (person,),
        )
        entry = one(
            owner,
            "insert into watchlist_entry (owner_id, watchlist_id, isin, venue)"
            " values (%s, %s, %s, 'NSE') returning id",
            (person, watchlist, HDFC_BANK),
        )
        found[username] = one(
            owner,
            "insert into watchlist_alert (owner_id, entry_id, rule, threshold)"
            " values (%s, %s, 'move_beyond', 0.02) returning id",
            (person, entry),
        )
    return found


def one(connection: psycopg.Connection, statement: str, values: tuple[Any, ...]) -> int:
    row = connection.execute(statement, values).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return int(row[0])


def owner_of(connection: psycopg.Connection, alert: int) -> int:
    return one(connection, "select owner_id from watchlist_alert where id = %s", (alert,))


def judge(
    connection: psycopg.Connection,
    alert: int,
    day: str,
    status: str = "watching",
    figure: float | None = 0.004,
    reason: str | None = None,
    known: str | None = None,
    person: int | None = None,
) -> None:
    connection.execute(
        JUDGE,
        {
            "owner": person or owner_of(connection, alert),
            "alert": alert,
            "day": day,
            "known": known or day,
            "status": status,
            "figure": figure,
            "reason": reason,
        },
    )


def refusal(error: pytest.ExceptionInfo[DBAPIError]) -> type[BaseException]:
    assert error.value.orig is not None
    return type(error.value.orig)


async def test_a_person_reads_their_own_verdicts_alone(
    database: Database, owner: psycopg.Connection, alerts: dict[str, int]
) -> None:
    judge(owner, alerts["asha"], "2025-12-30")
    judge(owner, alerts["asha"], "2025-12-31", "triggered", -0.023)

    async with database.transaction(owner_of(owner, alerts["asha"])) as session:
        own = [tuple(row) for row in await session.execute(VERDICTS)]
    async with database.transaction(owner_of(owner, alerts["ravi"])) as session:
        seen = (await session.execute(VERDICTS)).all()

    assert own == [("watching", 0.004), ("triggered", -0.023)]
    assert seen == []


@pytest.mark.parametrize(
    "statement",
    [
        API_JUDGE,
        "update watchlist_alert_evaluation set status = 'triggered'",
        "delete from watchlist_alert_evaluation",
    ],
)
async def test_the_api_s_role_writes_no_verdict(
    database: Database, owner: psycopg.Connection, alerts: dict[str, int], statement: str
) -> None:
    judge(owner, alerts["asha"], "2025-12-30")
    asha = owner_of(owner, alerts["asha"])

    with pytest.raises(DBAPIError) as refused:
        async with database.transaction(asha) as session:
            await session.execute(text(statement), {"owner": asha, "alert": alerts["asha"]})

    assert refusal(refused) is InsufficientPrivilege


def test_a_verdict_is_never_changed(owner: psycopg.Connection, alerts: dict[str, int]) -> None:
    judge(owner, alerts["asha"], "2025-12-31")

    with pytest.raises(RestrictViolation):
        owner.execute("update watchlist_alert_evaluation set status = 'triggered'")


def test_a_verdict_belongs_to_an_alert_of_the_same_person(
    owner: psycopg.Connection, alerts: dict[str, int]
) -> None:
    with pytest.raises(ForeignKeyViolation):
        judge(owner, alerts["asha"], "2025-12-31", person=owner_of(owner, alerts["ravi"]))


@pytest.mark.parametrize(
    ("status", "reason"),
    [("paused", None), ("watching", "not_traded"), ("triggered", "capital_action"), ("x", None)],
)
def test_a_paused_verdict_alone_carries_its_reason(
    owner: psycopg.Connection, alerts: dict[str, int], status: str, reason: str | None
) -> None:
    with pytest.raises(CheckViolation):
        judge(owner, alerts["asha"], "2025-12-31", status, None, reason)


def test_a_session_is_judged_once_for_each_day_its_figure_became_known(
    owner: psycopg.Connection, alerts: dict[str, int]
) -> None:
    judge(owner, alerts["asha"], "2025-12-31")
    judge(owner, alerts["asha"], "2025-12-31", "triggered", -0.021, known="2026-01-02")

    with pytest.raises(UniqueViolation):
        judge(owner, alerts["asha"], "2025-12-31", known="2026-01-02")
    with pytest.raises(CheckViolation):
        judge(owner, alerts["asha"], "2026-01-05", known="2026-01-02")
