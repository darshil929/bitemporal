"""Identity derived from the committed dataset, and written to the database."""

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from pipelines.identity import (
    derive_instruments,
    derive_listings,
    persist_identity,
    resolvable,
)
from pipelines.models.market import PriceBar

FIXTURE_SCHEMA = "fixture"

# The symbol in force on a bar's date comes from the listing covering that date, which is the
# resolution the whole identity model exists to make possible.
BAR_QUERY = (
    "select p.isin, p.venue, p.trade_date, p.as_of_date, l.local_symbol, l.scrip_code,"
    " p.open, p.high, p.low, p.close, p.previous_close, p.volume, p.turnover, p.trade_count"
    " from price_daily p join listing l"
    " on l.isin = p.isin and l.exchange = p.venue and p.trade_date >= l.listing_date"
    " and (l.delisting_date is null or p.trade_date <= l.delisting_date)"
)


@pytest.fixture(scope="module")
def seed(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        seeded_postgres, options=f"-csearch_path={FIXTURE_SCHEMA},public"
    ) as opened:
        yield opened


@pytest.fixture(scope="module")
def bars(seed: psycopg.Connection) -> tuple[PriceBar, ...]:
    columns = [
        "isin",
        "venue",
        "trade_date",
        "as_of_date",
        "local_symbol",
        "scrip_code",
        "open",
        "high",
        "low",
        "close",
        "previous_close",
        "volume",
        "turnover",
        "trade_count",
    ]
    rows = seed.execute(BAR_QUERY).fetchall()
    return tuple(PriceBar(**dict(zip(columns, row, strict=True))) for row in rows)


@pytest.fixture(scope="module")
def venue_last_day(bars: tuple[PriceBar, ...]) -> dict[str, date]:
    last: dict[str, date] = {}
    for item in bars:
        last[item.venue] = max(last.get(item.venue, item.trade_date), item.trade_date)
    return last


def test_every_bar_in_the_dataset_resolves(bars: tuple[PriceBar, ...]) -> None:
    assert resolvable(bars) == bars


def test_every_bar_resolves_to_exactly_one_listing(
    seed: psycopg.Connection, bars: tuple[PriceBar, ...]
) -> None:
    """A bar matching no listing has no symbol; one matching two has an ambiguous symbol."""
    stored = seed.execute("select count(*) from price_daily").fetchone()

    assert stored is not None
    assert len(bars) == stored[0]


def test_a_rename_is_recorded_on_both_venues(
    bars: tuple[PriceBar, ...], venue_last_day: dict[str, date]
) -> None:
    """An instrument renamed at one venue is renamed at the other; only the identifier differs."""
    listings = derive_listings(bars, venue_last_day)
    renamed = {item.isin for item in listings if item.closure_reason == "renamed"}

    assert renamed
    for isin in renamed:
        venues = {item.exchange for item in listings if item.isin == isin}
        if len(venues) < 2:
            continue
        per_venue = {
            venue: len([item for item in listings if item.isin == isin and item.exchange == venue])
            for venue in venues
        }
        assert min(per_venue.values()) > 1, f"{isin} lost a stretch at one venue"


def test_identity_written_twice_leaves_one_row_per_listing(
    migrated_connection: psycopg.Connection,
    bars: tuple[PriceBar, ...],
    venue_last_day: dict[str, date],
) -> None:
    names = {item.isin: item.local_symbol for item in bars}
    instruments = derive_instruments(bars, names)
    listings = derive_listings(bars, venue_last_day)

    persist_identity(migrated_connection, instruments, listings)
    persist_identity(migrated_connection, instruments, listings)

    counts = migrated_connection.execute(
        "select (select count(*) from instrument_master), (select count(*) from listing)"
    ).fetchone()

    assert counts == (len(instruments), len(listings))
