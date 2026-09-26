"""Derivation of instrument identity, listings and primary venue from observed bars."""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

import psycopg

from pipelines.models.identity import (
    InstrumentRecord,
    ListingRecord,
    PrimaryVenueRecord,
    SuccessionRecord,
)
from pipelines.models.market import PriceBar
from pipelines.sources.errors import SourceError

logger = logging.getLogger(__name__)

ISIN_PATTERN = re.compile("^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# A venue mislabels a row at a time. A file the parser has mistaken for another format names no
# instrument on nearly every row.
UNRESOLVED_SHARE = 0.01

# A listing that stops before the venue does has stopped trading rather than simply reached the
# end of the observed window.
SETTLED_AFTER = timedelta(days=90)

# A face value change issues a new ISIN, and the successor trades on the next day the venue is
# open under the identifier the venue keeps. A weekend beside a holiday fits inside this.
SUCCESSION_WINDOW = timedelta(days=7)

# Liquidity migrates between venues gradually, so the designation is recomputed monthly from the
# quarter behind it.
TURNOVER_WINDOW = timedelta(days=90)

# A fault reading the history loses stretches outright, while history reaching further back only
# moves the day a stretch begins.
VANISHED_SHARE = 0.01


class UnresolvedInstrument(SourceError):
    """A row names an instrument that cannot be resolved to an ISIN."""


class StaleIdentity(Exception):
    """Deriving identity again would lose stretches that history reaching further back cannot."""


@dataclass
class Spell:
    """A run of days one instrument traded under one symbol at one venue."""

    symbol: str
    scrip_code: str | None
    first_day: date
    last_day: date


@dataclass(frozen=True)
class Stretch:
    """One period a venue named one instrument one way, whether read from files or from storage."""

    isin: str
    exchange: str
    local_symbol: str
    scrip_code: str | None
    first_day: date
    last_day: date


def venue_key(bar: PriceBar) -> str:
    """The identifier that survives a rename at the venue.

    BSE keeps the scrip code when a ticker changes and lists the same instrument on more than one
    security line, so the code separates them. NSE publishes no such identifier, and its ticker is
    the thing that changes, so every NSE bar for an instrument belongs to one line.
    """
    return bar.scrip_code or ""


def extend_spell(history: list[Spell], bar: PriceBar) -> None:
    """Lengthen the open spell, or start one when the symbol has changed."""
    if history and history[-1].symbol == bar.local_symbol:
        history[-1].last_day = bar.trade_date
        return
    history.append(Spell(bar.local_symbol, bar.scrip_code, bar.trade_date, bar.trade_date))


def resolvable(bars: Iterable[PriceBar]) -> tuple[PriceBar, ...]:
    """Return the bars that name an instrument, leaving out the few that do not.

    BSE publishes a blank or NA in the ISIN column on a hundred or so rows across its history.
    Such a row names nothing to key a bar on and cannot be stored, so it is logged and left out
    rather than costing the day the rest of its bars.

    Past a small share the file is not what the parser takes it for, and the day is refused.
    """
    read = tuple(bars)
    unresolved = [bar for bar in read if not ISIN_PATTERN.match(bar.isin)]

    for bar in unresolved:
        logger.warning(
            "row names no instrument",
            extra={
                "venue": bar.venue,
                "trade_date": bar.trade_date.isoformat(),
                "identifier": bar.isin,
                "local_symbol": bar.local_symbol,
            },
        )

    if unresolved and len(unresolved) > UNRESOLVED_SHARE * len(read):
        named = sorted({bar.isin for bar in unresolved})
        raise UnresolvedInstrument(
            f"{len(unresolved)} of {len(read)} rows name no instrument: {named[:5]}"
        )

    return tuple(bar for bar in read if ISIN_PATTERN.match(bar.isin))


def derive_instruments(
    bars: Sequence[PriceBar], names: dict[str, str], country: str = "IN"
) -> tuple[InstrumentRecord, ...]:
    return tuple(
        InstrumentRecord(
            isin=isin, name=names.get(isin, isin), country=country, instrument_type="equity"
        )
        for isin in sorted({bar.isin for bar in bars})
    )


def derive_listings(
    bars: Sequence[PriceBar], venue_last_day: dict[str, date]
) -> tuple[ListingRecord, ...]:
    """Group bars into stretches and close each one the venue's own record ended."""
    spells: dict[tuple[str, str, str], list[Spell]] = defaultdict(list)

    for bar in sorted(bars, key=lambda item: (item.isin, item.venue, item.trade_date)):
        extend_spell(spells[(bar.isin, bar.venue, venue_key(bar))], bar)

    stretches = [
        Stretch(isin, venue, spell.symbol, spell.scrip_code, spell.first_day, spell.last_day)
        for (isin, venue, _), history in sorted(spells.items())
        for spell in history
    ]
    return close_listings(stretches, venue_last_day)


def close_listings(
    stretches: Sequence[Stretch], venue_last_day: dict[str, date]
) -> tuple[ListingRecord, ...]:
    """Turn observed stretches into listings, closing each one that ended.

    A stretch the venue kept trading past is closed as renamed when another follows it under the
    same venue-local identifier, and as delisted when none does, unless another ISIN took the
    instrument over, which supersedes it. A takeover closes the stretch at once, however recently
    it happened, since the instrument carries on under its new ISIN.
    """
    grouped: dict[tuple[str, str, str], list[Stretch]] = defaultdict(list)
    for stretch in stretches:
        grouped[(stretch.isin, stretch.exchange, stretch.scrip_code or "")].append(stretch)

    histories = {
        group: _absorb_untickered(sorted(history, key=lambda item: item.first_day), group[2])
        for group, history in sorted(grouped.items())
    }
    openings: dict[tuple[str, str], list[tuple[date, str]]] = defaultdict(list)
    for (isin, venue, _), history in histories.items():
        for stretch in history:
            openings[(venue, stretch.scrip_code or stretch.local_symbol)].append(
                (stretch.first_day, isin)
            )

    listings = []
    for (isin, venue, _), history in histories.items():
        for index, stretch in enumerate(history):
            renamed = index < len(history) - 1
            stopped = stretch.last_day < venue_last_day[venue] - SETTLED_AFTER
            taken_over = any(
                other != isin and stretch.last_day < opened <= stretch.last_day + SUCCESSION_WINDOW
                for opened, other in openings[(venue, stretch.scrip_code or stretch.local_symbol)]
            )
            closed = renamed or stopped or taken_over
            listings.append(
                ListingRecord(
                    isin=isin,
                    exchange=venue,
                    local_symbol=stretch.local_symbol,
                    scrip_code=stretch.scrip_code,
                    listing_date=stretch.first_day,
                    delisting_date=stretch.last_day if closed else None,
                    closure_reason=("renamed" if renamed else "delisted") if closed else None,
                )
            )

    return mark_supersessions(listings)


def venue_identifier(listing: ListingRecord) -> str:
    """What the venue keeps when the ISIN changes: the scrip code at BSE, the ticker at NSE."""
    return listing.scrip_code or listing.local_symbol


def mark_supersessions(listings: Sequence[ListingRecord]) -> tuple[ListingRecord, ...]:
    """Record a stretch that ended because a new ISIN took the instrument over.

    Shriram Finance stopped as `INE721A01013` on 2025-01-09 and resumed as `INE721A01047` the next
    day, keeping its scrip code and its ticker. The instrument never left the venue, so the stretch
    closes as superseded rather than delisted. Which ISIN succeeded it is recorded by
    `derive_successions`, which reads the same link.
    """
    openings = _openings(listings)

    return tuple(
        listing.model_copy(update={"closure_reason": "superseded"})
        if _successor(listing, openings) is not None
        else listing
        for listing in listings
    )


def derive_successions(listings: Sequence[ListingRecord]) -> tuple[SuccessionRecord, ...]:
    """Link each superseded stretch to the ISIN that took it over.

    Bajaj Finance stopped as `INE296A01024` on 2025-06-13 and resumed as `INE296A01032` on
    2025-06-16 under scrip code 500034 and ticker BAJFINANCE. Following that link is what lets a
    series run across a split, the predecessor holding every bar before it and no history of its
    own surviving under the successor.
    """
    openings = _openings(listings)
    successions = []

    for listing in listings:
        taken_over = _successor(listing, openings)
        if taken_over is None:
            continue
        changed_on, successor = taken_over
        successions.append(
            SuccessionRecord(
                predecessor_isin=listing.isin,
                exchange=listing.exchange,
                successor_isin=successor,
                changed_on=changed_on,
            )
        )

    return tuple(sorted(successions, key=lambda item: (item.predecessor_isin, item.exchange)))


def _openings(listings: Sequence[ListingRecord]) -> dict[tuple[str, str], list[tuple[date, str]]]:
    """Every day an ISIN began trading, by venue and by the identifier the venue keeps."""
    openings: dict[tuple[str, str], list[tuple[date, str]]] = defaultdict(list)
    for listing in listings:
        openings[(listing.exchange, venue_identifier(listing))].append(
            (listing.listing_date, listing.isin)
        )
    return openings


def _successor(
    listing: ListingRecord, openings: dict[tuple[str, str], list[tuple[date, str]]]
) -> tuple[date, str] | None:
    """The ISIN that opened under the same identifier as this stretch closed, if one did.

    A stretch already closed as renamed continued under the same ISIN, so only one closed as
    delisted, or recognised as superseded on an earlier pass, can have been taken over.
    """
    closed_on = listing.delisting_date
    if listing.closure_reason not in ("delisted", "superseded") or closed_on is None:
        return None

    taken_over = [
        (opened_on, isin)
        for opened_on, isin in openings[(listing.exchange, venue_identifier(listing))]
        if isin != listing.isin and closed_on < opened_on <= closed_on + SUCCESSION_WINDOW
    ]
    return min(taken_over) if taken_over else None


def _absorb_untickered(history: list[Stretch], key: str) -> list[Stretch]:
    """Fold a stretch that carried no ticker into the one that follows it.

    The BSE file published no ticker before the cutover, so those rows report the scrip code as
    the symbol. They belong to the stretch that names the instrument rather than forming one of
    their own, and folding them keeps every bar inside a listing.
    """
    if len(history) >= 2 and history[0].local_symbol == key:
        widened = replace(history[1], first_day=history[0].first_day)
        return [widened, *history[2:]]
    return history


def _computation_days(first: date, last: date) -> list[date]:
    """Month ends inside the range, and the final observed day when it is not one."""
    days, current = [], date(first.year, first.month, 1)
    while current <= last:
        following = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        days.append(following - timedelta(days=1))
        current = following

    inside = [day for day in days if first <= day <= last]
    if last not in inside:
        inside.append(last)
    return inside


class TradedValue(Protocol):
    """What designating a primary venue needs of a row: who traded where, when, and how much.

    Read-only members, so a bar read from a file and a summary read from storage both satisfy it.
    """

    @property
    def isin(self) -> str: ...

    @property
    def venue(self) -> str: ...

    @property
    def trade_date(self) -> date: ...

    @property
    def turnover(self) -> Decimal | None: ...


def derive_primary_venue(bars: Sequence[TradedValue]) -> tuple[PrimaryVenueRecord, ...]:
    """Designate, month by month, the venue an instrument's series is computed from.

    The designation carries the date it was computed, so a backtest reads the venue that trailing
    turnover pointed at on the date in question rather than the one it points at now.
    """
    if not bars:
        return ()

    by_day: dict[tuple[str, str, date], Decimal] = defaultdict(Decimal)
    for bar in bars:
        by_day[(bar.isin, bar.venue, bar.trade_date)] += bar.turnover or Decimal(0)

    first = min(bar.trade_date for bar in bars)
    last = max(bar.trade_date for bar in bars)

    designations: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for computed_on in _computation_days(first, last):
        window_opens = computed_on - TURNOVER_WINDOW
        totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for (isin, venue, day), turnover in by_day.items():
            if window_opens < day <= computed_on:
                totals[(isin, venue)] += turnover

        leaders: dict[str, tuple[Decimal, str]] = {}
        for (isin, venue), turnover in totals.items():
            best = leaders.get(isin)
            if best is None or turnover > best[0] or (turnover == best[0] and venue < best[1]):
                leaders[isin] = (turnover, venue)

        for isin, (_, venue) in leaders.items():
            designations[isin].append((computed_on, venue))

    return tuple(_collapse(designations))


def _collapse(designations: dict[str, list[tuple[date, str]]]) -> list[PrimaryVenueRecord]:
    """Fold consecutive months that agree into one span."""
    records = []
    for isin in sorted(designations):
        months = designations[isin]
        start_index = 0
        for index in range(1, len(months) + 1):
            ended = index == len(months) or months[index][1] != months[start_index][1]
            if not ended:
                continue
            computed_on, venue = months[start_index]
            closes = index < len(months)
            records.append(
                PrimaryVenueRecord(
                    isin=isin,
                    effective_from=computed_on,
                    as_of_date=computed_on,
                    effective_to=months[index][0] if closes else None,
                    venue=venue,
                )
            )
            start_index = index
    return records


def persist_identity(
    connection: psycopg.Connection,
    instruments: Sequence[InstrumentRecord],
    listings: Sequence[ListingRecord],
    venues: Sequence[PrimaryVenueRecord],
    successions: Sequence[SuccessionRecord] = (),
) -> None:
    """Write identity rows, leaving anything already recorded in place."""
    for instrument in instruments:
        connection.execute(
            "insert into instrument_master (isin, name, country, instrument_type)"
            " values (%s, %s, %s, %s) on conflict (isin) do update set name = excluded.name",
            (instrument.isin, instrument.name, instrument.country, instrument.instrument_type),
        )

    for listing in listings:
        connection.execute(
            "insert into listing"
            " (isin, exchange, local_symbol, scrip_code, listing_date, delisting_date,"
            " closure_reason) values (%s, %s, %s, %s, %s, %s, %s)"
            " on conflict (isin, exchange, local_symbol, listing_date) do update set"
            " delisting_date = excluded.delisting_date,"
            " closure_reason = excluded.closure_reason",
            (
                listing.isin,
                listing.exchange,
                listing.local_symbol,
                listing.scrip_code,
                listing.listing_date,
                listing.delisting_date,
                listing.closure_reason,
            ),
        )

    for venue in venues:
        connection.execute(
            "insert into instrument_primary_venue"
            " (isin, effective_from, as_of_date, effective_to, venue) values (%s, %s, %s, %s, %s)"
            " on conflict (isin, effective_from, as_of_date) do nothing",
            (venue.isin, venue.effective_from, venue.as_of_date, venue.effective_to, venue.venue),
        )

    for succession in successions:
        connection.execute(
            "insert into instrument_succession"
            " (predecessor_isin, exchange, successor_isin, changed_on) values (%s, %s, %s, %s)"
            " on conflict (predecessor_isin, exchange) do update set"
            " successor_isin = excluded.successor_isin, changed_on = excluded.changed_on",
            (
                succession.predecessor_isin,
                succession.exchange,
                succession.successor_isin,
                succession.changed_on,
            ),
        )

    logger.info(
        "identity written",
        extra={
            "instruments": len(instruments),
            "listings": len(listings),
            "primary_venues": len(venues),
            "successions": len(successions),
        },
    )


def retire_listings(connection: psycopg.Connection, listings: Sequence[ListingRecord]) -> int:
    """Remove stored stretches that the whole history no longer derives.

    A stretch is keyed on the day it begins. History reaching further back, such as a session held
    before an instrument's first stored day, derives the stretch again under an earlier first day,
    and the row it began on before would otherwise overlap it.
    """
    derived = {
        (listing.isin, listing.exchange, listing.local_symbol, listing.listing_date)
        for listing in listings
    }
    stored = connection.execute(
        "select listing_id, isin, exchange, local_symbol, listing_date from listing"
    ).fetchall()
    continuing = {(listing.isin, listing.exchange, listing.local_symbol) for listing in listings}
    stale = [row for row in stored if (row[1], row[2], row[3], row[4]) not in derived]
    vanished = [row for row in stale if (row[1], row[2], row[3]) not in continuing]

    if len(vanished) > VANISHED_SHARE * len(stored):
        raise StaleIdentity(
            f"deriving identity would lose {len(vanished)} of {len(stored)} stored stretches"
        )
    if stale:
        connection.execute(
            "delete from listing where listing_id = any(%s)", ([row[0] for row in stale],)
        )
        logger.info("listing stretches no longer derived removed", extra={"stretches": len(stale)})
    return len(stale)
