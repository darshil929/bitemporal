"""Derivation of instrument identity, listings and primary venue from observed bars."""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from pipelines.models.identity import InstrumentRecord, ListingRecord, PrimaryVenueRecord
from pipelines.models.market import PriceBar
from pipelines.sources.errors import SourceError

logger = logging.getLogger(__name__)

ISIN_PATTERN = re.compile("^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# A listing that stops before the venue does has stopped trading rather than simply reached the
# end of the observed window.
SETTLED_AFTER = timedelta(days=90)

# Liquidity migrates between venues gradually, so the designation is recomputed monthly from the
# quarter behind it.
TURNOVER_WINDOW = timedelta(days=90)


class UnresolvedInstrument(SourceError):
    """A row names an instrument that cannot be resolved to an ISIN."""


@dataclass
class Spell:
    """A stretch during which one instrument traded under one symbol at one venue."""

    symbol: str
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


def require_resolvable(bars: Iterable[PriceBar]) -> tuple[PriceBar, ...]:
    """Return the bars unchanged, refusing any whose ISIN is not one.

    A row that cannot be resolved is a defect in the source or the parser. Dropping it would
    quietly shrink the universe, so it stops the ingestion instead.
    """
    checked = tuple(bars)
    unresolved = sorted({bar.isin for bar in checked if not ISIN_PATTERN.match(bar.isin)})
    if unresolved:
        raise UnresolvedInstrument(f"{len(unresolved)} identifiers are not ISINs: {unresolved[:5]}")
    return checked


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
    """Group bars into stretches, closing one whenever the symbol changes."""
    spells: dict[tuple[str, str, str], list[Spell]] = defaultdict(list)

    for bar in sorted(bars, key=lambda item: (item.isin, item.venue, item.trade_date)):
        extend_spell(spells[(bar.isin, bar.venue, venue_key(bar))], bar)

    listings = []
    for (isin, venue, key), history in sorted(spells.items()):
        history = _absorb_untickered(history, key)
        for index, spell in enumerate(history):
            renamed = index < len(history) - 1
            stopped = spell.last_day < venue_last_day[venue] - SETTLED_AFTER
            closed = renamed or stopped
            listings.append(
                ListingRecord(
                    isin=isin,
                    exchange=venue,
                    local_symbol=spell.symbol,
                    scrip_code=spell.scrip_code,
                    listing_date=spell.first_day,
                    delisting_date=spell.last_day if closed else None,
                    closure_reason=("renamed" if renamed else "delisted") if closed else None,
                )
            )

    return tuple(listings)


def _absorb_untickered(history: list[Spell], key: str) -> list[Spell]:
    """Fold a stretch that carried no ticker into the one that follows it.

    The BSE file published no ticker before the cutover, so those rows report the scrip code as
    the symbol. They belong to the stretch that names the instrument rather than forming one of
    their own, and folding them keeps every bar inside a listing.
    """
    if len(history) >= 2 and history[0].symbol == key:
        history[1].first_day = history[0].first_day
        return history[1:]
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


def derive_primary_venue(bars: Sequence[PriceBar]) -> tuple[PrimaryVenueRecord, ...]:
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

    logger.info(
        "identity written",
        extra={
            "instruments": len(instruments),
            "listings": len(listings),
            "primary_venues": len(venues),
        },
    )
