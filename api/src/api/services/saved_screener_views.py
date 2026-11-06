"""A person's saved screens of the daily features: each kept under a name, saved over, renamed, and
removed by marking it removed."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode

from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.db.database import Database
from api.services.screener_queries import ScreenRefused, screen_from

# The parts of a screen's address, in the order a saved view keeps them; the page is left out.
PARTS = ("gate", "kind", "c", "sort")

COLUMNS = "id, name, query, created_at, updated_at"
VIEWS = text(
    f"select {COLUMNS} from screener_view where removed_at is null order by lower(name), id"
)
SAVE = text(
    "insert into screener_view (owner_id, name, query) values (:owner, :name, :query)"
    f" returning {COLUMNS}"
)
CHANGE = text(
    "update screener_view set name = coalesce(:name, name), query = coalesce(:query, query),"
    f" updated_at = now() where id = :id and removed_at is null returning {COLUMNS}"
)
REMOVE = text(
    "update screener_view set removed_at = now() where id = :id and removed_at is null returning id"
)


@dataclass
class ViewRefused(Exception):
    """A view whose name the person keeps already, or that the person keeps no longer or never."""

    reason: str


@dataclass(frozen=True)
class SavedView:
    id: int
    name: str
    query: str
    created_at: datetime
    updated_at: datetime


def kept_query(query: str) -> str:
    """The screen an address asks for as a view keeps it, refused as the screener refuses it: its
    parts in a fixed order, the default kind and the page left out."""
    named: defaultdict[str, list[str]] = defaultdict(list)
    for name, value in parse_qsl(query, keep_blank_values=True):
        if name not in (*PARTS, "page"):
            raise ScreenRefused("unknown_parameter", name)
        named[name].append(value)
    for name in ("gate", "kind", "sort"):
        if len(named[name]) > 1:
            raise ScreenRefused("repeated_parameter", name)
    gate, kind, sort = (next(iter(named[name]), None) for name in ("gate", "kind", "sort"))
    if kind not in (None, "companies", "all"):
        raise ScreenRefused("unknown_kind", kind)
    screen_from(gate, "all" if kind == "all" else "companies", named["c"], sort, 1)
    parts = [("gate", gate)] if gate is not None else []
    parts += [("kind", "all")] if kind == "all" else []
    parts += [("c", part) for part in named["c"]]
    parts += [("sort", sort)] if sort is not None else []
    return urlencode(parts, safe=":")


async def saved_views(database: Database, owner: int) -> list[SavedView]:
    async with database.transaction(owner) as transaction:
        return [SavedView(*row) for row in await transaction.execute(VIEWS)]


async def save_view(database: Database, owner: int, name: str, query: str) -> SavedView:
    try:
        async with database.transaction(owner) as transaction:
            saved = await transaction.execute(
                SAVE, {"owner": owner, "name": name, "query": kept_query(query)}
            )
            return SavedView(*saved.one())
    except IntegrityError as error:
        if isinstance(error.orig, UniqueViolation):
            raise ViewRefused("view_name_taken") from error
        raise


async def change_view(
    database: Database, owner: int, view_id: int, name: str | None, query: str | None
) -> SavedView:
    """The view renamed, saved over with another screen, or both."""
    kept = None if query is None else kept_query(query)
    try:
        async with database.transaction(owner) as transaction:
            changed = await transaction.execute(
                CHANGE, {"id": view_id, "name": name, "query": kept}
            )
            row = changed.one_or_none()
    except IntegrityError as error:
        if isinstance(error.orig, UniqueViolation):
            raise ViewRefused("view_name_taken") from error
        raise
    if row is None:
        raise ViewRefused("view_not_found")
    return SavedView(*row)


async def remove_view(database: Database, owner: int, view_id: int) -> None:
    async with database.transaction(owner) as transaction:
        removed = (await transaction.execute(REMOVE, {"id": view_id})).one_or_none()
    if removed is None:
        raise ViewRefused("view_not_found")
