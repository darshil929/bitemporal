"""A person's saved screens as the API's role reaches them."""

from collections.abc import AsyncIterator

import psycopg
import pytest
from psycopg.errors import CheckViolation, InsufficientPrivilege, UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.config import ApiSettings
from api.db.database import Database
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

SAVE = text(
    "insert into screener_view (owner_id, name, query) values (:owner, :name, :query) returning id"
)
NAMES = text("select owner_id, name from screener_view where removed_at is null order by name")
REMOVE = text("update screener_view set removed_at = now() where id = :id")
RENAME = text("update screener_view set name = :name where id = :id returning id")
RISING = "gate=adtv_20d:gte:250000000&c=return_3m:gt:0&c=delivery_pct_20d:gt:50"


@pytest.fixture
async def database(migrated_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(migrated_settings)
    yield opened
    await opened.close()


@pytest.fixture
def people(migrated_settings: ApiSettings, postgres_dsn: str) -> dict[str, int]:
    """Two accounts, written by the owner of the tables."""
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        accounts = {
            username: connection.execute(
                "insert into app_user (username, display_name, role, password_hash)"
                " values (%s, %s, 'member', 'unused') returning id",
                (username, username.title()),
            ).fetchone()[0]  # type: ignore[index]
            for username in ("asha", "ravi")
        }
        connection.commit()
    return accounts


async def save(database: Database, owner: int, name: str, query: str = RISING) -> int:
    async with database.transaction(owner) as session:
        saved: int = (
            await session.execute(SAVE, {"owner": owner, "name": name, "query": query})
        ).scalar_one()
    return saved


def refusal(error: pytest.ExceptionInfo[DBAPIError]) -> type[BaseException]:
    assert error.value.orig is not None
    return type(error.value.orig)


async def test_a_person_s_views_are_theirs_alone(
    database: Database, people: dict[str, int]
) -> None:
    asha, ravi = people["asha"], people["ravi"]
    rising = await save(database, asha, "Rising with delivery")

    async with database.transaction(ravi) as session:
        seen = (await session.execute(NAMES)).all()
        renamed = (await session.execute(RENAME, {"name": "Taken", "id": rising})).all()
    async with database.transaction(asha) as session:
        own = [tuple(row) for row in await session.execute(NAMES)]

    assert (seen, renamed) == ([], [])
    assert own == [(asha, "Rising with delivery")]


async def test_a_person_cannot_keep_a_view_under_another_s_name(
    database: Database, people: dict[str, int]
) -> None:
    with pytest.raises(DBAPIError) as refused:
        async with database.transaction(people["ravi"]) as session:
            await session.execute(SAVE, {"owner": people["asha"], "name": "Planted", "query": ""})

    assert "row-level security" in str(refused.value.orig)


async def test_the_api_s_role_removes_a_view_by_marking_it_and_deletes_nothing(
    database: Database, people: dict[str, int]
) -> None:
    asha = people["asha"]
    rising = await save(database, asha, "Rising with delivery")

    with pytest.raises(DBAPIError) as refused:
        async with database.transaction(asha) as session:
            await session.execute(text("delete from screener_view where id = :id"), {"id": rising})
    async with database.transaction(asha) as session:
        await session.execute(REMOVE, {"id": rising})
        kept = (await session.execute(NAMES)).all()

    assert refusal(refused) is InsufficientPrivilege
    assert kept == []


async def test_a_name_is_kept_once_per_person_whatever_its_case_and_freed_on_removal(
    database: Database, people: dict[str, int]
) -> None:
    asha, ravi = people["asha"], people["ravi"]
    rising = await save(database, asha, "Rising with delivery")

    with pytest.raises(DBAPIError) as taken:
        await save(database, asha, "rising WITH delivery")
    await save(database, ravi, "Rising with delivery")
    async with database.transaction(asha) as session:
        await session.execute(REMOVE, {"id": rising})
    await save(database, asha, "rising with delivery")

    assert refusal(taken) is UniqueViolation


@pytest.mark.parametrize("name", ["", " Padded", "Padded ", "x" * 81])
async def test_a_name_is_trimmed_text_of_one_to_eighty_characters(
    database: Database, people: dict[str, int], name: str
) -> None:
    with pytest.raises(DBAPIError) as refused:
        await save(database, people["asha"], name)

    assert refusal(refused) is CheckViolation


async def test_a_view_holds_a_screen_of_at_most_two_thousand_characters(
    database: Database, people: dict[str, int]
) -> None:
    await save(database, people["asha"], "Default screen", "")

    with pytest.raises(DBAPIError) as refused:
        await save(database, people["asha"], "Too long", "c=" + "x" * 1999)

    assert refusal(refused) is CheckViolation
