"""What needs a person's attention on the published day: their alerts the newest session triggered,
the venues whose session that day failed its checks, and, among the instruments their watchlists
hold, a divergence between the venues, an ISIN replaced at a change of face value, and corporate
actions no factor adjusts within the sessions a month's return reads."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services import watchlist_management
from api.services.market_reads import read_marts
from api.services.price_history import number
from api.services.watchlist_daily_reads import (
    IDENTITIES,
    LATEST_VERDICTS,
    PUBLISHED,
    VENUE_SESSIONS,
    Verdict,
)
from api.services.watchlist_management import Entry

# The sessions a 1-month return spans, over which an unadjusted action distorts it.
UNHANDLED_SESSIONS = 21

INCOMPLETE = text(
    "select venue, divergent_instruments, detail from mart_trading_days"
    " where trade_date = :day and not is_complete order by venue"
)
WINDOW_START = text(
    "select min(trade_date) from (select distinct trade_date from mart_trading_days"
    " where trade_date <= :day order by trade_date desc limit :sessions) as recent"
)
DIVERGING = text(
    "select isin, venue_spread_bps from mart_daily_features"
    " where trade_date = :day and is_diverging and isin = any(:currents)"
)
UNHANDLED = text(
    "select isin, ex_date, purpose from mart_corporate_actions where action_type = 'unhandled'"
    " and ex_date >= :since and ex_date <= :day and isin = any(:currents) order by ex_date, isin"
)


@dataclass(frozen=True)
class TriggeredAlert:
    entry_id: int
    watchlist_id: int
    isin: str
    display_name: str | None
    venue: str
    rule: str
    threshold: Decimal
    trade_date: date
    figure: float | None


@dataclass(frozen=True)
class IncompleteSession:
    venue: str
    trade_date: date
    divergent_instruments: int
    detail: str | None


@dataclass(frozen=True)
class Divergence:
    isin: str
    display_name: str | None
    venue_spread_bps: float | None


@dataclass(frozen=True)
class SupersededEntry:
    entry_id: int
    watchlist_id: int
    isin: str
    display_name: str | None
    superseded_by: str


@dataclass(frozen=True)
class UnhandledAction:
    isin: str
    display_name: str | None
    ex_date: date
    purpose: str | None


@dataclass(frozen=True)
class Attention:
    """Each kind empty where nothing needs attention."""

    published_day: date | None
    alerts: tuple[TriggeredAlert, ...] = ()
    incomplete_sessions: tuple[IncompleteSession, ...] = ()
    divergences: tuple[Divergence, ...] = ()
    superseded: tuple[SupersededEntry, ...] = ()
    unhandled_actions: tuple[UnhandledAction, ...] = ()


@dataclass(frozen=True)
class MarketFacts:
    published_day: date | None
    identities: dict[str, Any]
    venue_sessions: dict[str, date]
    incomplete: list[Any]
    diverging: dict[str, float | None]
    unhandled: list[Any]


def attention(
    entries: tuple[Entry, ...], verdicts: dict[int, Verdict], facts: MarketFacts
) -> Attention:
    """The feed from a person's entries, their alerts' latest verdicts and the day's market facts;
    an instrument held in several lists listed once."""
    names = {isin: row.display_name for isin, row in facts.identities.items()}
    current = {isin: row.current_isin for isin, row in facts.identities.items()}
    alerts = []
    for entry in entries:
        verdict = verdicts.get(entry.alert.id) if entry.alert else None
        newest = facts.venue_sessions.get(entry.venue)
        if (
            entry.alert
            and verdict
            and verdict.status == "triggered"
            and verdict.trade_date == newest
        ):
            alerts.append(
                TriggeredAlert(
                    entry.id,
                    entry.watchlist_id,
                    entry.isin,
                    names.get(entry.isin),
                    entry.venue,
                    entry.alert.rule,
                    entry.alert.threshold,
                    verdict.trade_date,
                    verdict.figure,
                )
            )
    held = {current.get(entry.isin, entry.isin): entry for entry in entries}
    superseded = {
        entry.isin: SupersededEntry(
            entry.id, entry.watchlist_id, entry.isin, names.get(entry.isin), current[entry.isin]
        )
        for entry in entries
        if current.get(entry.isin, entry.isin) != entry.isin
    }
    return Attention(
        published_day=facts.published_day,
        alerts=tuple(alerts),
        incomplete_sessions=tuple(
            IncompleteSession(row.venue, facts.published_day, row.divergent_instruments, row.detail)
            for row in facts.incomplete
            if facts.published_day
        ),
        divergences=tuple(
            Divergence(isin, names.get(isin), spread)
            for isin, spread in facts.diverging.items()
            if isin in held
        ),
        superseded=tuple(superseded.values()),
        unhandled_actions=tuple(
            UnhandledAction(row.isin, names.get(row.isin), row.ex_date, row.purpose)
            for row in facts.unhandled
            if row.isin in held
        ),
    )


async def _market_facts(transaction: AsyncSession, entries: tuple[Entry, ...]) -> MarketFacts:
    published = (await transaction.execute(PUBLISHED)).scalar_one_or_none()
    isins = sorted({entry.isin for entry in entries})
    identities = {row.isin: row for row in await transaction.execute(IDENTITIES, {"isins": isins})}
    currents = sorted({row.current_isin for row in identities.values()})
    if published is None:
        return MarketFacts(None, identities, {}, [], {}, [])
    day = {"day": published}
    since = (
        await transaction.execute(WINDOW_START, day | {"sessions": UNHANDLED_SESSIONS})
    ).scalar_one()
    on_day = day | {"currents": currents}
    return MarketFacts(
        published_day=published,
        identities=identities,
        venue_sessions=dict(
            (await transaction.execute(VENUE_SESSIONS, {"published": published})).tuples().all()
        ),
        incomplete=list(await transaction.execute(INCOMPLETE, day)),
        diverging={
            row.isin: number(row.venue_spread_bps)
            for row in await transaction.execute(DIVERGING, on_day)
        },
        unhandled=list(
            await transaction.execute(UNHANDLED, on_day | {"since": since or published})
        ),
    )


async def attention_feed(database: Database, owner: int) -> Attention:
    kept = await watchlist_management.watchlists(database, owner)
    entries = tuple(entry for watchlist in kept for entry in watchlist.entries)
    alerts = [entry.alert.id for entry in entries if entry.alert]
    async with database.transaction(owner) as transaction:
        verdicts = {
            row.alert_id: Verdict(*row[1:])
            for row in await transaction.execute(LATEST_VERDICTS, {"alerts": alerts})
        }

    async def read(transaction: AsyncSession) -> MarketFacts:
        return await _market_facts(transaction, entries)

    return attention(entries, verdicts, await read_marts(database, read))
