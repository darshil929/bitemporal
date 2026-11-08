"""A person's watchlists: each kept under a name, renamed, and removed by marking it removed. The
earliest list a person keeps is their default."""

from dataclasses import dataclass
from datetime import datetime

from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database

LIST_LIMIT = 20

# Held to the end of the transaction, so a person's lists are counted and added one change at a
# time: two requests at once can neither pass the limit nor both add a first list.
PERSON_LOCK = text("select pg_advisory_xact_lock(hashtext('watchlist'), :owner)")

COLUMNS = "id, name, id = min(id) over () as is_default, created_at, updated_at"
LISTS = text(
    f"select {COLUMNS} from watchlist where removed_at is null"
    " order by is_default desc, lower(name), id"
)
KEPT_COUNT = text("select count(*) from watchlist where removed_at is null")
ADD = text("insert into watchlist (owner_id, name) values (:owner, :name) returning id")
RENAME = text(
    "update watchlist set name = :name, updated_at = now()"
    " where id = :id and removed_at is null returning id"
)
REMOVE = text(
    "update watchlist set removed_at = now() where id = :id and removed_at is null returning id"
)


@dataclass
class WatchlistRefused(Exception):
    """A list whose name the person keeps already, one past the limit, or one the person keeps no
    longer or never."""

    reason: str


@dataclass(frozen=True)
class Watchlist:
    id: int
    name: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


async def _kept_list(transaction: AsyncSession, watchlist_id: int) -> Watchlist:
    for row in await transaction.execute(LISTS):
        if row.id == watchlist_id:
            return Watchlist(*row)
    raise WatchlistRefused("watchlist_not_found")


async def watchlists(database: Database, owner: int) -> list[Watchlist]:
    async with database.transaction(owner) as transaction:
        return [Watchlist(*row) for row in await transaction.execute(LISTS)]


async def add_watchlist(database: Database, owner: int, name: str) -> Watchlist:
    try:
        async with database.transaction(owner) as transaction:
            await transaction.execute(PERSON_LOCK, {"owner": owner})
            if (await transaction.execute(KEPT_COUNT)).scalar_one() >= LIST_LIMIT:
                raise WatchlistRefused("watchlist_limit_reached")
            added = (await transaction.execute(ADD, {"owner": owner, "name": name})).scalar_one()
            return await _kept_list(transaction, added)
    except IntegrityError as error:
        if isinstance(error.orig, UniqueViolation):
            raise WatchlistRefused("watchlist_name_taken") from error
        raise


async def rename_watchlist(
    database: Database, owner: int, watchlist_id: int, name: str
) -> Watchlist:
    try:
        async with database.transaction(owner) as transaction:
            renamed = await transaction.execute(RENAME, {"id": watchlist_id, "name": name})
            if renamed.one_or_none() is None:
                raise WatchlistRefused("watchlist_not_found")
            return await _kept_list(transaction, watchlist_id)
    except IntegrityError as error:
        if isinstance(error.orig, UniqueViolation):
            raise WatchlistRefused("watchlist_name_taken") from error
        raise


async def remove_watchlist(database: Database, owner: int, watchlist_id: int) -> None:
    async with database.transaction(owner) as transaction:
        removed = (await transaction.execute(REMOVE, {"id": watchlist_id})).one_or_none()
    if removed is None:
        raise WatchlistRefused("watchlist_not_found")
