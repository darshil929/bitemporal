"""A person's watchlists, their entries and alerts as the API's role reaches them."""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from psycopg.errors import (
    CheckViolation,
    ForeignKeyViolation,
    InsufficientPrivilege,
    UniqueViolation,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from api.config import ApiSettings
from api.db.database import Database
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

HDFC_BANK = "INE040A01034"
INFOSYS = "INE009A01021"

ADD_LIST = "insert into watchlist (owner_id, name) values (:owner, :name) returning id"
ADD_ENTRY = (
    "insert into watchlist_entry (owner_id, watchlist_id, isin, venue)"
    " values (:owner, :list, :isin, :venue) returning id"
)
ADD_ALERT = (
    "insert into watchlist_alert (owner_id, entry_id, rule, threshold)"
    " values (:owner, :entry, :rule, :threshold) returning id"
)
TABLES = ("watchlist", "watchlist_entry", "watchlist_alert")


@pytest.fixture
async def database(migrated_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(migrated_settings)
    yield opened
    await opened.close()


@pytest.fixture
def people(migrated_settings: ApiSettings, postgres_dsn: str) -> dict[str, int]:
    """Two accounts and two instruments, written by the owner of the tables."""
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        connection.execute(
            "insert into instrument_master (isin, name, country, instrument_type)"
            " values (%s, 'HDFC Bank Ltd', 'IN', 'equity'), (%s, 'Infosys Ltd', 'IN', 'equity')",
            (HDFC_BANK, INFOSYS),
        )
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


async def run(database: Database, person: int, statement: str, **values: Any) -> list[Any]:
    async with database.transaction(person) as session:
        result = await session.execute(text(statement), values)
        return list(result.scalars()) if result.returns_rows else []


async def add(database: Database, owner: int, statement: str, **values: Any) -> int:
    (added,) = await run(database, owner, statement, owner=owner, **values)
    return int(added)


async def followed(database: Database, owner: int) -> dict[str, int]:
    """A list holding one entry on NSE with an alert on a move beyond 2%."""
    watchlist = await add(database, owner, ADD_LIST, name="Watchlist")
    entry = await add(database, owner, ADD_ENTRY, list=watchlist, isin=HDFC_BANK, venue="NSE")
    alert = await add(database, owner, ADD_ALERT, entry=entry, rule="move_beyond", threshold=0.02)
    return {"watchlist": watchlist, "watchlist_entry": entry, "watchlist_alert": alert}


async def end(database: Database, person: int, table: str, row: int) -> None:
    await run(database, person, f"update {table} set ended_at = now() where id = :id", id=row)


def refusal(error: pytest.ExceptionInfo[DBAPIError]) -> type[BaseException]:
    assert error.value.orig is not None
    return type(error.value.orig)


async def test_a_person_s_lists_entries_and_alerts_are_theirs_alone(
    database: Database, people: dict[str, int]
) -> None:
    asha, ravi = people["asha"], people["ravi"]
    kept = await followed(database, asha)

    seen = {table: await run(database, ravi, f"select id from {table}") for table in TABLES}
    changed = [
        await run(database, ravi, "update watchlist set name = 'Taken' where true returning id"),
        await run(database, ravi, "update watchlist_entry set ended_at = now() returning id"),
        await run(database, ravi, "update watchlist_alert set ended_at = now() returning id"),
    ]
    own = {table: await run(database, asha, f"select id from {table}") for table in TABLES}

    assert seen == {table: [] for table in TABLES}
    assert changed == [[], [], []]
    assert own == {table: [kept[table]] for table in TABLES}


async def test_an_entry_or_alert_joins_only_a_list_or_entry_of_the_same_person(
    database: Database, people: dict[str, int]
) -> None:
    asha, ravi = people["asha"], people["ravi"]
    kept = await followed(database, asha)

    # Refused as a list that does not exist, never as an instrument the list already holds.
    with pytest.raises(DBAPIError) as entry_refused:
        await add(database, ravi, ADD_ENTRY, list=kept["watchlist"], isin=HDFC_BANK, venue="NSE")
    with pytest.raises(DBAPIError) as alert_refused:
        entry = kept["watchlist_entry"]
        await add(database, ravi, ADD_ALERT, entry=entry, rule="close_above", threshold=900)

    assert refusal(entry_refused) is ForeignKeyViolation
    assert refusal(alert_refused) is ForeignKeyViolation


@pytest.mark.parametrize(
    "statement",
    [
        *(f"delete from {table}" for table in TABLES),
        "update watchlist_entry set venue = 'BSE'",
        f"update watchlist_entry set isin = '{INFOSYS}'",
        "update watchlist_alert set rule = 'close_above'",
        "update watchlist_alert set threshold = 0.05",
    ],
)
async def test_the_api_s_role_deletes_nothing_and_ends_rather_than_changes_an_entry_or_alert(
    database: Database, people: dict[str, int], statement: str
) -> None:
    asha = people["asha"]
    await followed(database, asha)

    with pytest.raises(DBAPIError) as refused:
        await run(database, asha, statement)

    assert refusal(refused) is InsufficientPrivilege


async def test_a_list_name_is_kept_once_per_person_whatever_its_case_and_freed_on_removal(
    database: Database, people: dict[str, int]
) -> None:
    asha, ravi = people["asha"], people["ravi"]
    banks = await add(database, asha, ADD_LIST, name="Private banks")

    with pytest.raises(DBAPIError) as taken:
        await add(database, asha, ADD_LIST, name="PRIVATE banks")
    await add(database, ravi, ADD_LIST, name="Private banks")
    await run(database, asha, "update watchlist set removed_at = now() where id = :id", id=banks)
    await add(database, asha, ADD_LIST, name="private banks")

    assert refusal(taken) is UniqueViolation


@pytest.mark.parametrize("name", ["", " Padded", "Padded ", "x" * 81])
async def test_a_list_name_is_trimmed_text_of_one_to_eighty_characters(
    database: Database, people: dict[str, int], name: str
) -> None:
    with pytest.raises(DBAPIError) as refused:
        await add(database, people["asha"], ADD_LIST, name=name)

    assert refusal(refused) is CheckViolation


async def test_an_instrument_is_kept_once_in_a_list_whatever_its_venue(
    database: Database, people: dict[str, int]
) -> None:
    asha = people["asha"]
    kept = await followed(database, asha)
    other = await add(database, asha, ADD_LIST, name="Other")

    with pytest.raises(DBAPIError) as taken:
        await add(database, asha, ADD_ENTRY, list=kept["watchlist"], isin=HDFC_BANK, venue="BSE")
    await add(database, asha, ADD_ENTRY, list=other, isin=HDFC_BANK, venue="NSE")
    await end(database, asha, "watchlist_entry", kept["watchlist_entry"])
    await add(database, asha, ADD_ENTRY, list=kept["watchlist"], isin=HDFC_BANK, venue="BSE")

    assert refusal(taken) is UniqueViolation


async def test_an_entry_holds_one_open_alert_and_keeps_the_rules_it_ended(
    database: Database, people: dict[str, int]
) -> None:
    asha = people["asha"]
    kept = await followed(database, asha)
    entry = kept["watchlist_entry"]

    with pytest.raises(DBAPIError) as taken:
        await add(database, asha, ADD_ALERT, entry=entry, rule="close_above", threshold=900)
    await end(database, asha, "watchlist_alert", kept["watchlist_alert"])
    await add(database, asha, ADD_ALERT, entry=entry, rule="close_above", threshold=900)
    rules = await run(database, asha, "select rule from watchlist_alert order by id")

    assert refusal(taken) is UniqueViolation
    assert rules == ["move_beyond", "close_above"]


@pytest.mark.parametrize(
    ("rule", "threshold"),
    [("move_beyond", 0), ("spread_above", -5), ("delivery_above", 100), ("price_above", 900)],
)
async def test_an_alert_holds_a_known_rule_and_a_threshold_it_can_cross(
    database: Database, people: dict[str, int], rule: str, threshold: float
) -> None:
    asha = people["asha"]
    kept = await followed(database, asha)
    await end(database, asha, "watchlist_alert", kept["watchlist_alert"])

    with pytest.raises(DBAPIError) as refused:
        await add(
            database, asha, ADD_ALERT, entry=kept["watchlist_entry"], rule=rule, threshold=threshold
        )

    assert refusal(refused) is CheckViolation
