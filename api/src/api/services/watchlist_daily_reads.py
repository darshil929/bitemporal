"""A watchlist's entries as the page shows them: each instrument's newest session at the entry's venue
up to the published day, its figures that session, and its alert with the latest verdict."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services import watchlist_management
from api.services.market_reads import read_marts
from api.services.price_history import number
from api.services.watchlist_management import Alert, Entry, Watchlist, WatchlistRefused

PUBLISHED = text("select trade_date from feature_release order by release_id desc limit 1")
IDENTITIES = text(
    "select instruments.isin, instruments.current_isin, instruments.display_name,"
    " primary_venues.primary_venue from mart_instruments as instruments"
    " left join mart_primary_venue as primary_venues on primary_venues.isin = instruments.isin"
    " where instruments.isin = any(:isins)"
)
# The symbol shown is the one of the newest stretch at the entry's venue.
SYMBOLS = text(
    "select distinct on (isin, exchange) isin, exchange, local_symbol from mart_listings"
    " where isin = any(:isins) order by isin, exchange, listing_date desc"
)
# Each instrument's newest session at each venue, traded under its own ISIN; a replaced ISIN's bars
# stop at the change. Bounded below, the read stays in the newest chunks of the price table; the
# instruments it finds nothing for are looked for over the whole history.
RECENT_WINDOW = timedelta(days=45)
LAST_SESSIONS = text(
    "select isin, venue, max(trade_date) from mart_price_daily where isin = any(:isins)"
    " and trade_date <= :published and trade_date > :since group by isin, venue"
)
VENUE_SESSIONS = text(
    "select venue, max(trade_date) from mart_trading_days where trade_date <= :published"
    " group by venue"
)
CLOSES = text(
    "select isin, venue, trade_date, close from mart_price_daily"
    " where isin = any(:isins) and trade_date = any(:days)"
)
# The figures follow the series of the ISIN that took a replaced one over, which holds its bars.
FIGURES = text(
    "select isin, venue, trade_date, change_1d, return_1d, return_1m, delivery_pct_1d"
    " from mart_venue_daily_figures where isin = any(:currents) and trade_date = any(:days)"
)
# Read apart from the figures: joined to them, the grouped view is not narrowed to the instruments.
SPREADS = text(
    "select isin, trade_date, venue_spread_bps from mart_venue_spread"
    " where isin = any(:isins) and trade_date = any(:days)"
)
DIVERGING = text(
    "select isin, trade_date, is_diverging from mart_daily_features"
    " where isin = any(:currents) and trade_date = any(:days)"
)
LATEST_VERDICTS = text(
    "select distinct on (alert_id) alert_id, trade_date, status, figure, paused_reason"
    " from watchlist_alert_evaluation where alert_id = any(:alerts)"
    " order by alert_id, trade_date desc, as_of_date desc"
)


@dataclass(frozen=True)
class Verdict:
    """The alert's verdict on the latest session judged."""

    trade_date: date
    status: str
    figure: float | None
    paused_reason: str | None


@dataclass(frozen=True)
class WatchlistRow:
    """An entry on its venue's newest session up to the published day; every figure absent where
    the instrument never traded there. `is_stale` where the venue held a later session."""

    entry_id: int
    isin: str
    venue: str
    display_name: str | None
    local_symbol: str | None
    primary_venue: str | None
    superseded_by: str | None
    trade_date: date | None
    is_stale: bool | None
    close: float | None
    change_1d: float | None
    return_1d: float | None
    return_1m: float | None
    delivery_pct_1d: float | None
    venue_spread_bps: float | None
    is_diverging: bool | None
    alert: Alert | None
    verdict: Verdict | None


@dataclass(frozen=True)
class WatchlistRows:
    watchlist: Watchlist
    published_day: date | None
    rows: tuple[WatchlistRow, ...]

    @property
    def triggered(self) -> int:
        return sum(
            row.verdict is not None and row.verdict.status == "triggered" for row in self.rows
        )


@dataclass(frozen=True)
class MarketFacts:
    published_day: date | None
    identities: dict[str, Any]
    symbols: dict[tuple[str, str], str]
    last_sessions: dict[tuple[str, str], date]
    venue_sessions: dict[str, date]
    closes: dict[tuple[str, str, date], Any]
    figures: dict[tuple[str, str, date], Any]
    spreads: dict[tuple[str, date], Any]
    diverging: dict[tuple[str, date], bool | None]


def venue_day(row: Any) -> tuple[str, str, date]:
    return row.isin, row.venue, row.trade_date


async def _market_facts(transaction: AsyncSession, entries: tuple[Entry, ...]) -> MarketFacts:
    published = (await transaction.execute(PUBLISHED)).scalar_one_or_none()
    isins = sorted({entry.isin for entry in entries})
    identities = {row.isin: row for row in await transaction.execute(IDENTITIES, {"isins": isins})}
    currents = sorted({row.current_isin for row in identities.values()})
    scope = {"isins": isins, "published": published or date.max}
    recent = scope | {"since": (published or date.max) - RECENT_WINDOW}
    last_sessions = {
        (isin, venue): day for isin, venue, day in await transaction.execute(LAST_SESSIONS, recent)
    }
    unfound = sorted(
        {entry.isin for entry in entries if (entry.isin, entry.venue) not in last_sessions}
    )
    if unfound:
        older = scope | {"isins": unfound, "since": date.min}
        last_sessions |= {
            (isin, venue): day
            for isin, venue, day in await transaction.execute(LAST_SESSIONS, older)
        }
    days = sorted(set(last_sessions.values()))
    on_days = {"isins": isins, "currents": currents, "days": days}
    return MarketFacts(
        published_day=published,
        identities=identities,
        symbols={
            (isin, venue): symbol
            for isin, venue, symbol in await transaction.execute(SYMBOLS, {"isins": isins})
        },
        last_sessions=last_sessions,
        venue_sessions=dict((await transaction.execute(VENUE_SESSIONS, scope)).tuples().all()),
        closes={venue_day(row): row for row in await transaction.execute(CLOSES, on_days)},
        figures={venue_day(row): row for row in await transaction.execute(FIGURES, on_days)},
        spreads={
            (row.isin, row.trade_date): row for row in await transaction.execute(SPREADS, on_days)
        },
        diverging={
            (row.isin, row.trade_date): row.is_diverging
            for row in await transaction.execute(DIVERGING, on_days)
        },
    )


def _row(entry: Entry, facts: MarketFacts, verdict: Verdict | None) -> WatchlistRow:
    identity = facts.identities.get(entry.isin)
    current = identity.current_isin if identity else entry.isin
    day = facts.last_sessions.get((entry.isin, entry.venue))
    close = facts.closes.get((entry.isin, entry.venue, day)) if day else None
    figures = facts.figures.get((current, entry.venue, day)) if day else None
    spread = facts.spreads.get((entry.isin, day)) if day else None
    latest = facts.venue_sessions.get(entry.venue)
    return WatchlistRow(
        entry_id=entry.id,
        isin=entry.isin,
        venue=entry.venue,
        display_name=identity.display_name if identity else None,
        local_symbol=facts.symbols.get((entry.isin, entry.venue)),
        primary_venue=identity.primary_venue if identity else None,
        superseded_by=current if current != entry.isin else None,
        trade_date=day,
        is_stale=None if day is None or latest is None else day < latest,
        close=number(close.close) if close else None,
        change_1d=figures.change_1d if figures else None,
        return_1d=figures.return_1d if figures else None,
        return_1m=figures.return_1m if figures else None,
        delivery_pct_1d=figures.delivery_pct_1d if figures else None,
        venue_spread_bps=number(spread.venue_spread_bps) if spread else None,
        is_diverging=facts.diverging.get((current, day)) if day else None,
        alert=entry.alert,
        verdict=verdict,
    )


async def watchlist_rows(database: Database, owner: int, watchlist_id: int) -> WatchlistRows:
    kept = await watchlist_management.watchlists(database, owner)
    watchlist = next((listed for listed in kept if listed.id == watchlist_id), None)
    if watchlist is None:
        raise WatchlistRefused("watchlist_not_found")
    alerts = [entry.alert.id for entry in watchlist.entries if entry.alert]
    async with database.transaction(owner) as transaction:
        verdicts = {
            row.alert_id: Verdict(*row[1:])
            for row in await transaction.execute(LATEST_VERDICTS, {"alerts": alerts})
        }

    async def read(transaction: AsyncSession) -> MarketFacts:
        return await _market_facts(transaction, watchlist.entries)

    facts = await read_marts(database, read)
    rows = tuple(
        _row(entry, facts, verdicts.get(entry.alert.id) if entry.alert else None)
        for entry in watchlist.entries
    )
    return WatchlistRows(watchlist, facts.published_day, rows)
