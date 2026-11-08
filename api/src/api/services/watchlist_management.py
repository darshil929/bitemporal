"""A person's watchlists: each kept under a name, renamed, and removed by marking it removed, and the
instruments each follows on one venue. The earliest list a person keeps is their default. An entry
ends rather than being deleted, and a change of venue ends it and starts another. An entry holds one
alert at a time; a changed rule ends the alert and starts another."""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from psycopg.errors import UniqueViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts

LIST_LIMIT = 20
ENTRY_LIMIT = 500
DEFAULT_LIST_NAME = "Watchlist"
# The venue an entry follows when none is asked for and the instrument has no primary venue, in the
# order the instrument search shows a symbol.
VENUE_PREFERENCE = ("NSE", "BSE")

# Held to the end of the transaction, so a person's lists and entries are counted and added one
# change at a time: two requests at once can neither pass a limit nor both add a first list.
PERSON_LOCK = text("select pg_advisory_xact_lock(hashtext('watchlist'), :owner)")

COLUMNS = "id, name, id = min(id) over () as is_default, created_at, updated_at"
LISTS = text(
    f"select {COLUMNS} from watchlist where removed_at is null"
    " order by is_default desc, lower(name), id"
)
KEPT_COUNT = text("select count(*) from watchlist where removed_at is null")
DEFAULT_LIST = text("select id from watchlist where removed_at is null order by id limit 1")
KEPT_LIST = text("select id from watchlist where id = :id and removed_at is null")
ADD = text("insert into watchlist (owner_id, name) values (:owner, :name) returning id")
RENAME = text(
    "update watchlist set name = :name, updated_at = now()"
    " where id = :id and removed_at is null returning id"
)
REMOVE = text(
    "update watchlist set removed_at = now() where id = :id and removed_at is null returning id"
)

ENTRY_COLUMNS = "id, watchlist_id, isin, venue, added_at"
# Each entry with its open alert, where it has one.
ENTRIES = text(
    """
    select
        entries.id, entries.watchlist_id, entries.isin, entries.venue, entries.added_at,
        alerts.id as alert_id, alerts.rule, alerts.threshold, alerts.created_at as alert_created_at
    from watchlist_entry as entries
    left join watchlist_alert as alerts on alerts.entry_id = entries.id and alerts.ended_at is null
    where entries.ended_at is null
    order by entries.added_at, entries.id
    """
)
KEPT_ENTRY_COUNT = text(
    "select count(*) from watchlist_entry where watchlist_id = :list and ended_at is null"
)
ADD_ENTRY = text(
    "insert into watchlist_entry (owner_id, watchlist_id, isin, venue)"
    f" values (:owner, :list, :isin, :venue) returning {ENTRY_COLUMNS}"
)
KEPT_ENTRY = text(
    f"select {ENTRY_COLUMNS} from watchlist_entry where id = :id and ended_at is null"
)
END_ENTRY = text(
    "update watchlist_entry set ended_at = now() where id = :id and ended_at is null"
    f" returning {ENTRY_COLUMNS}"
)
END_LIST_ENTRIES = text(
    "update watchlist_entry set ended_at = now() where watchlist_id = :list and ended_at is null"
)

ALERT_COLUMNS = "id, rule, threshold, created_at"
OPEN_ALERT = text(
    f"select {ALERT_COLUMNS} from watchlist_alert where entry_id = :entry and ended_at is null"
)
ADD_ALERT = text(
    "insert into watchlist_alert (owner_id, entry_id, rule, threshold)"
    f" values (:owner, :entry, :rule, :threshold) returning {ALERT_COLUMNS}"
)
END_ALERT = text(
    "update watchlist_alert set ended_at = now() where entry_id = :entry and ended_at is null"
    f" returning {ALERT_COLUMNS}"
)
END_LIST_ALERTS = text(
    "update watchlist_alert set ended_at = now() where ended_at is null"
    " and entry_id in (select id from watchlist_entry where watchlist_id = :list)"
)

LISTED_VENUES = text(
    """
    select
        array(
            select distinct exchange from mart_listings
            where isin = :isin and delisting_date is null order by exchange
        ) as venues,
        (select primary_venue from mart_primary_venue where isin = :isin) as primary_venue
    """
)


@dataclass
class WatchlistRefused(Exception):
    """A change the person's lists or entries do not admit: a name or instrument kept already, one
    past a limit, a venue the instrument is not listed on, or a list or entry the person keeps no
    longer or never."""

    reason: str


@dataclass(frozen=True)
class Alert:
    """The rule an entry's alert evaluates, in the unit the daily figures hold: a move as a fraction,
    delivery in percent, the spread in basis points, a close in rupees."""

    id: int
    rule: str
    threshold: Decimal
    created_at: datetime


@dataclass(frozen=True)
class Entry:
    id: int
    watchlist_id: int
    isin: str
    venue: str
    added_at: datetime
    alert: Alert | None = None


@dataclass(frozen=True)
class Watchlist:
    id: int
    name: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
    entries: tuple[Entry, ...] = field(default=())


@dataclass(frozen=True)
class ListedVenues:
    """The venues an instrument is listed on now, and its primary venue where one is known."""

    venues: tuple[str, ...]
    primary_venue: str | None


def chosen_venue(listed: ListedVenues, asked: str | None) -> str:
    """The venue an entry follows: the one asked for, else the primary, else the only one."""
    if not listed.venues:
        raise WatchlistRefused("instrument_not_listed")
    if asked is not None:
        if asked not in listed.venues:
            raise WatchlistRefused("venue_not_listed")
        return asked
    if listed.primary_venue in listed.venues:
        return listed.primary_venue
    return next((venue for venue in VENUE_PREFERENCE if venue in listed.venues), listed.venues[0])


async def listed_venues(database: Database, isin: str) -> ListedVenues:
    async def read(transaction: AsyncSession) -> ListedVenues:
        row = (await transaction.execute(LISTED_VENUES, {"isin": isin})).one()
        return ListedVenues(tuple(row.venues), row.primary_venue)

    return await read_marts(database, read)


async def _kept_list(transaction: AsyncSession, watchlist_id: int) -> Watchlist:
    for row in await transaction.execute(LISTS):
        if row.id == watchlist_id:
            return Watchlist(*row)
    raise WatchlistRefused("watchlist_not_found")


async def _list_for_entry(transaction: AsyncSession, owner: int, watchlist_id: int | None) -> int:
    """The list asked for, else the default, which a person keeping no list gains."""
    if watchlist_id is not None:
        kept = (await transaction.execute(KEPT_LIST, {"id": watchlist_id})).scalar_one_or_none()
        if kept is None:
            raise WatchlistRefused("watchlist_not_found")
        return int(kept)
    default = (await transaction.execute(DEFAULT_LIST)).scalar_one_or_none()
    if default is None:
        default = (
            await transaction.execute(ADD, {"owner": owner, "name": DEFAULT_LIST_NAME})
        ).scalar_one()
    return int(default)


async def watchlists(database: Database, owner: int) -> list[Watchlist]:
    async with database.transaction(owner) as transaction:
        kept = [Watchlist(*row) for row in await transaction.execute(LISTS)]
        entries: defaultdict[int, list[Entry]] = defaultdict(list)
        for row in await transaction.execute(ENTRIES):
            alert = None
            if row.alert_id is not None:
                alert = Alert(row.alert_id, row.rule, row.threshold, row.alert_created_at)
            entries[row.watchlist_id].append(replace(Entry(*row[:5]), alert=alert))
    return [replace(watchlist, entries=tuple(entries[watchlist.id])) for watchlist in kept]


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
    """The list marked removed, and every entry it holds ended with its alert."""
    async with database.transaction(owner) as transaction:
        removed = (await transaction.execute(REMOVE, {"id": watchlist_id})).one_or_none()
        if removed is None:
            raise WatchlistRefused("watchlist_not_found")
        await transaction.execute(END_LIST_ALERTS, {"list": watchlist_id})
        await transaction.execute(END_LIST_ENTRIES, {"list": watchlist_id})


async def add_entry(
    database: Database, owner: int, isin: str, venue: str | None, watchlist_id: int | None
) -> Entry:
    """The instrument added to a list on the venue asked for, else its primary venue."""
    chosen = chosen_venue(await listed_venues(database, isin), venue)
    try:
        async with database.transaction(owner) as transaction:
            await transaction.execute(PERSON_LOCK, {"owner": owner})
            target = await _list_for_entry(transaction, owner, watchlist_id)
            counted = await transaction.execute(KEPT_ENTRY_COUNT, {"list": target})
            if counted.scalar_one() >= ENTRY_LIMIT:
                raise WatchlistRefused("entry_limit_reached")
            added = await transaction.execute(
                ADD_ENTRY, {"owner": owner, "list": target, "isin": isin, "venue": chosen}
            )
            return Entry(*added.one())
    except IntegrityError as error:
        if isinstance(error.orig, UniqueViolation):
            raise WatchlistRefused("instrument_already_listed") from error
        raise


async def change_entry_venue(database: Database, owner: int, entry_id: int, venue: str) -> Entry:
    """The entry ended and its instrument followed on another venue from now, in the same list, its
    alert carried across; the entry itself where it follows that venue already."""
    async with database.transaction(owner) as transaction:
        row = (await transaction.execute(KEPT_ENTRY, {"id": entry_id})).one_or_none()
        alert = (await transaction.execute(OPEN_ALERT, {"entry": entry_id})).one_or_none()
    if row is None:
        raise WatchlistRefused("entry_not_found")
    kept = replace(Entry(*row), alert=Alert(*alert) if alert else None)
    if kept.venue == venue:
        return kept
    chosen = chosen_venue(await listed_venues(database, kept.isin), venue)
    async with database.transaction(owner) as transaction:
        await transaction.execute(PERSON_LOCK, {"owner": owner})
        if (await transaction.execute(END_ENTRY, {"id": entry_id})).one_or_none() is None:
            raise WatchlistRefused("entry_not_found")
        ended = (await transaction.execute(END_ALERT, {"entry": entry_id})).one_or_none()
        added = await transaction.execute(
            ADD_ENTRY,
            {"owner": owner, "list": kept.watchlist_id, "isin": kept.isin, "venue": chosen},
        )
        moved = Entry(*added.one())
        if ended is None:
            return moved
        return replace(moved, alert=await _add_alert(transaction, owner, moved.id, *ended[1:3]))


async def remove_entry(database: Database, owner: int, entry_id: int) -> None:
    async with database.transaction(owner) as transaction:
        ended = (await transaction.execute(END_ENTRY, {"id": entry_id})).one_or_none()
        await transaction.execute(END_ALERT, {"entry": entry_id})
    if ended is None:
        raise WatchlistRefused("entry_not_found")


async def _add_alert(
    transaction: AsyncSession, owner: int, entry_id: int, rule: str, threshold: Decimal
) -> Alert:
    added = await transaction.execute(
        ADD_ALERT, {"owner": owner, "entry": entry_id, "rule": rule, "threshold": threshold}
    )
    return Alert(*added.one())


async def set_alert(
    database: Database, owner: int, entry_id: int, rule: str, threshold: Decimal
) -> Alert:
    """The entry's alert from now: the open one where it holds this rule already, else a new one,
    ending any other."""
    async with database.transaction(owner) as transaction:
        await transaction.execute(PERSON_LOCK, {"owner": owner})
        if (await transaction.execute(KEPT_ENTRY, {"id": entry_id})).one_or_none() is None:
            raise WatchlistRefused("entry_not_found")
        row = (await transaction.execute(OPEN_ALERT, {"entry": entry_id})).one_or_none()
        if row is not None and (row.rule, row.threshold) == (rule, threshold):
            return Alert(*row)
        await transaction.execute(END_ALERT, {"entry": entry_id})
        return await _add_alert(transaction, owner, entry_id, rule, threshold)


async def remove_alert(database: Database, owner: int, entry_id: int) -> None:
    async with database.transaction(owner) as transaction:
        if (await transaction.execute(KEPT_ENTRY, {"id": entry_id})).one_or_none() is None:
            raise WatchlistRefused("entry_not_found")
        if (await transaction.execute(END_ALERT, {"entry": entry_id})).one_or_none() is None:
            raise WatchlistRefused("alert_not_found")
