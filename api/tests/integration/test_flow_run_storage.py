"""Flow runs and their steps as the launcher records them and the API's role reads them."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
from psycopg.errors import CheckViolation, InsufficientPrivilege, RestrictViolation, UniqueViolation
from psycopg.types.json import Jsonb
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.config import ApiSettings
from api.db.database import Database
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

RUN_ID = "5d74bcd9-0000-4000-8000-000000000001"
RECORD_RUN = (
    "insert into flow_run (run_id, flow, first_day, last_day, started_at, ended_at, outcome,"
    " counts, checks_passed, failures, warned_checks, failed_checks)"
    " values (%(run)s, %(flow)s, %(first)s, %(last)s, '2026-11-09 07:24:07+00',"
    " '2026-11-09 07:46:25+00', %(outcome)s, %(counts)s, 131, %(failures)s, %(warned)s,"
    " %(failed)s)"
)
RECORD_STEP = (
    "insert into flow_run_step (run_id, step, started_at, ended_at, outcome)"
    " values (%(run)s, %(step)s, %(started)s, '2026-11-09 07:30:00+00', %(outcome)s)"
)
BSE_PRICES = {"published": 5, "unpublished": 2, "outside_coverage": 0, "failed": 0}
SHORT_ANSWER = {
    "source": "bse_corporate_actions",
    "key": "20260101-20261231",
    "detail": "answer for 20260101-20261231 lacks 96 actions already stored",
}
WARNED = {"name": "assert_capital_actions_reported_by_both_venues", "rows": 16}


@pytest.fixture
async def database(migrated_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(migrated_settings)
    yield opened
    await opened.close()


@pytest.fixture
def owner(migrated_settings: ApiSettings, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    """The tables' owner, which records runs as the launcher does."""
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", autocommit=True
    ) as connection:
        yield connection


@pytest.fixture
def account(owner: psycopg.Connection) -> int:
    row = owner.execute(
        "insert into app_user (username, display_name, role, password_hash)"
        " values ('asha', 'Asha', 'member', 'unused') returning id"
    ).fetchone()
    assert row is not None
    return int(row[0])


def record_run(connection: psycopg.Connection, **changed: Any) -> None:
    values = {
        "run": RUN_ID,
        "flow": "sync",
        "first": "2026-11-03",
        "last": "2026-11-09",
        "outcome": "failed",
        "counts": Jsonb({"bse_bhavcopy": BSE_PRICES}),
        "failures": Jsonb([SHORT_ANSWER]),
        "warned": Jsonb([WARNED]),
        "failed": Jsonb([]),
    }
    connection.execute(RECORD_RUN, values | changed)


def record_step(connection: psycopg.Connection, **changed: Any) -> None:
    values = {
        "run": RUN_ID,
        "step": "bse_bhavcopy",
        "started": "2026-11-09 07:25:00+00",
        "outcome": "succeeded",
    }
    connection.execute(RECORD_STEP, values | changed)


def refusal(error: pytest.ExceptionInfo[DBAPIError]) -> type[BaseException]:
    assert error.value.orig is not None
    return type(error.value.orig)


async def test_the_api_s_role_reads_a_run_and_its_steps(
    database: Database, owner: psycopg.Connection, account: int
) -> None:
    record_run(owner)
    record_step(owner)
    record_step(owner, step="dbt_models", started=None, outcome="skipped")

    async with database.transaction(account) as session:
        run = (
            await session.execute(
                text("select outcome, counts, failures, warned_checks from flow_run")
            )
        ).one()
        steps = (
            await session.execute(text("select step, outcome from flow_run_step order by step"))
        ).all()

    assert tuple(run) == (
        "failed",
        {"bse_bhavcopy": BSE_PRICES},
        [SHORT_ANSWER],
        [WARNED],
    )
    assert [tuple(step) for step in steps] == [
        ("bse_bhavcopy", "succeeded"),
        ("dbt_models", "skipped"),
    ]


@pytest.mark.parametrize(
    "statement",
    [
        (
            "insert into flow_run_step (run_id, step, ended_at, outcome)"
            " values ('x', 'y', now(), 'skipped')"
        ),
        "update flow_run set outcome = 'succeeded'",
        "delete from flow_run",
        "delete from flow_run_step",
    ],
)
async def test_the_api_s_role_records_no_run(
    database: Database, owner: psycopg.Connection, account: int, statement: str
) -> None:
    record_run(owner)
    record_step(owner)

    with pytest.raises(DBAPIError) as refused:
        async with database.transaction(account) as session:
            await session.execute(text(statement))

    assert refusal(refused) is InsufficientPrivilege


@pytest.mark.parametrize(
    "statement",
    ["update flow_run set outcome = 'succeeded'", "update flow_run_step set outcome = 'failed'"],
)
def test_a_recorded_run_is_never_changed(owner: psycopg.Connection, statement: str) -> None:
    record_run(owner)
    record_step(owner)

    with pytest.raises(RestrictViolation):
        owner.execute(statement)


def test_a_step_is_recorded_before_its_run(owner: psycopg.Connection) -> None:
    record_step(owner)
    record_run(owner)

    with pytest.raises(UniqueViolation):
        record_step(owner)


@pytest.mark.parametrize(
    "changed",
    [
        {"outcome": "succeeded"},
        {"outcome": "succeeded", "failures": Jsonb([]), "failed": Jsonb([WARNED])},
        {"outcome": "interrupted"},
        {"flow": "backfill"},
        {"first": "2026-11-10"},
        {"counts": Jsonb([])},
    ],
)
def test_a_run_s_record_agrees_with_its_report(
    owner: psycopg.Connection, changed: dict[str, Any]
) -> None:
    with pytest.raises(CheckViolation):
        record_run(owner, **changed)


def test_a_success_may_carry_warned_checks(owner: psycopg.Connection) -> None:
    record_run(owner, outcome="succeeded", failures=Jsonb([]))


@pytest.mark.parametrize(
    "changed",
    [
        {"started": None},
        {"outcome": "skipped"},
        {"started": "2026-11-09 07:31:00+00"},
        {"outcome": "cancelled"},
    ],
)
def test_a_step_s_record_agrees_with_its_outcome(
    owner: psycopg.Connection, changed: dict[str, Any]
) -> None:
    with pytest.raises(CheckViolation):
        record_step(owner, **changed)
