"""What needs a person's attention on the published day: their alerts the newest session triggered,
and the entries whose ISIN a change of face value replaced."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services import watchlist_management
from api.services.market_reads import read_marts
from api.services.watchlist_daily_reads import (
    IDENTITIES,
    LATEST_VERDICTS,
    PUBLISHED,
    VENUE_SESSIONS,
    Verdict,
)
from api.services.watchlist_management import Entry


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
class SupersededEntry:
    entry_id: int
    watchlist_id: int
    isin: str
    display_name: str | None
    superseded_by: str


@dataclass(frozen=True)
class Attention:
    """Each kind empty where nothing needs attention."""

    published_day: date | None
    alerts: tuple[TriggeredAlert, ...] = ()
    superseded: tuple[SupersededEntry, ...] = ()


@dataclass(frozen=True)
class MarketFacts:
    published_day: date | None
    identities: dict[str, Any]
    venue_sessions: dict[str, date]


def attention(
    entries: tuple[Entry, ...], verdicts: dict[int, Verdict], facts: MarketFacts
) -> Attention:
    """The feed from a person's entries, their alerts' latest verdicts and the day's market facts;
    an ISIN held in several lists listed once."""
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
        superseded=tuple(superseded.values()),
    )


async def _market_facts(transaction: AsyncSession, entries: tuple[Entry, ...]) -> MarketFacts:
    published = (await transaction.execute(PUBLISHED)).scalar_one_or_none()
    isins = sorted({entry.isin for entry in entries})
    identities = {row.isin: row for row in await transaction.execute(IDENTITIES, {"isins": isins})}
    sessions = await transaction.execute(VENUE_SESSIONS, {"published": published or date.max})
    return MarketFacts(published, identities, dict(sessions.tuples().all()))


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
