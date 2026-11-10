"""Flow requests as admins add them through the API's role and the flows move them on."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
from psycopg.errors import CheckViolation, InsufficientPrivilege
from psycopg.types.json import Jsonb
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.config import ApiSettings
from api.db.database import Database
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

REQUEST = text(
    "insert into flow_request (flow, first_day, last_day, requested_by)"
    " values ('sync', '2026-11-04', '2026-11-10', :person) returning id, status"
)
REQUESTS = text("select flow, requested_by, status from flow_request order by id")
STATUSES = {
    "refused": "update flow_request set status = 'refused'",
    "started": "update flow_request set status = 'started'",
    "finished": "update flow_request set status = 'finished', started_at = now()",
}


@pytest.fixture
async def database(migrated_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(migrated_settings)
    yield opened
    await opened.close()


@pytest.fixture
def owner(migrated_settings: ApiSettings, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    """The tables' owner, which moves requests on as the flows do."""
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public", autocommit=True
    ) as connection:
        yield connection


@pytest.fixture
def people(owner: psycopg.Connection) -> dict[str, int]:
    """An admin and a member, by role."""
    found = {}
    for role in ("admin", "member"):
        row = owner.execute(
            "insert into app_user (username, display_name, role, password_hash)"
            " values (%s, %s, %s, 'unused') returning id",
            (f"a{role}", role.title(), role),
        ).fetchone()
        assert row is not None
        found[role] = int(row[0])
    return found


def refusal(error: pytest.ExceptionInfo[DBAPIError]) -> type[BaseException]:
    assert error.value.orig is not None
    return type(error.value.orig)


async def request_as(database: Database, person: int, named: int | None = None) -> Any:
    async with database.transaction(person) as session:
        return (await session.execute(REQUEST, {"person": named or person})).one()


async def test_an_admin_requests_a_run_everyone_signed_in_reads(
    database: Database, people: dict[str, int]
) -> None:
    added = await request_as(database, people["admin"])

    async with database.transaction(people["member"]) as session:
        seen = [tuple(row) for row in await session.execute(REQUESTS)]

    assert added.status == "requested"
    assert seen == [("sync", people["admin"], "requested")]


@pytest.mark.parametrize(("person", "named"), [("member", "member"), ("admin", "member")])
async def test_a_request_is_an_admin_s_own(
    database: Database, people: dict[str, int], person: str, named: str
) -> None:
    with pytest.raises(DBAPIError) as refused:
        await request_as(database, people[person], people[named])

    assert refusal(refused) is InsufficientPrivilege


@pytest.mark.parametrize(
    "statement",
    ["update flow_request set status = 'started', started_at = now()", "delete from flow_request"],
)
async def test_the_api_s_role_moves_no_request_on(
    database: Database, people: dict[str, int], statement: str
) -> None:
    await request_as(database, people["admin"])

    with pytest.raises(DBAPIError) as refused:
        async with database.transaction(people["admin"]) as session:
            await session.execute(text(statement))

    assert refusal(refused) is InsufficientPrivilege


@pytest.mark.parametrize("change", list(STATUSES))
async def test_a_request_s_status_agrees_with_its_record(
    database: Database, owner: psycopg.Connection, people: dict[str, int], change: str
) -> None:
    """A refusal carries its reason, a start its time, a finish both times."""
    await request_as(database, people["admin"])

    with pytest.raises(CheckViolation):
        owner.execute(STATUSES[change])


async def test_a_refused_request_keeps_the_reason_and_its_facts(
    database: Database, owner: psycopg.Connection, people: dict[str, int]
) -> None:
    added = await request_as(database, people["admin"])
    why = {"reason": "flow_running", "run_id": "47d6f98e", "first_day": "2026-11-03"}

    owner.execute(
        "update flow_request set status = 'refused', refusal = %s where id = %s",
        (Jsonb(why), added.id),
    )

    assert owner.execute("select refusal from flow_request").fetchone() == (why,)
