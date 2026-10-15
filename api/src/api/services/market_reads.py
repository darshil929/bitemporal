"""Reads of the market data a sync rebuilds while the application serves it."""

from collections.abc import Awaitable, Callable

import anyio
from psycopg.errors import UndefinedTable
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database

# A sync replaces a table by dropping the old one with every view over it, then builds each of those
# views again before it moves on.
MART_REBUILD_WAIT_SECONDS = 2.0


class MartMissing(Exception):
    """A read found a mart absent."""


class MarketDataUpdating(Exception):
    """A mart a read needs was still absent once the wait for its rebuild had passed."""


async def wait_for_rebuild() -> None:
    await anyio.sleep(MART_REBUILD_WAIT_SECONDS)


async def read_once[T](database: Database, read: Callable[[AsyncSession], Awaitable[T]]) -> T:
    try:
        async with database.transaction() as transaction:
            return await read(transaction)
    except ProgrammingError as error:
        if isinstance(error.orig, UndefinedTable):
            raise MartMissing from error
        raise


async def read_marts[T](database: Database, read: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """The answer of `read`, run in a transaction of its own; a read finding a mart absent runs once
    more after the wait for a rebuild."""
    try:
        return await read_once(database, read)
    except MartMissing:
        await wait_for_rebuild()
    try:
        return await read_once(database, read)
    except MartMissing as missing:
        raise MarketDataUpdating from missing
