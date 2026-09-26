"""Identity rebuilt from stored bars, against the dataset the builder derived from the same days."""

from collections.abc import Iterator
from datetime import timedelta

import psycopg
import pytest
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.identity import instrument_identity
from pipelines.checks.identity import (
    every_bar_sits_inside_a_listing,
    every_superseded_listing_names_its_successor,
)
from pipelines.history import read_stretches, venue_last_days
from pipelines.identity import StaleIdentity, close_listings, derive_successions, retire_listings

FIXTURE_SCHEMA = "fixture"

BAJAJ_OLD = "INE296A01024"
ETERNAL = "INE758T01015"
# NSDL listed in August 2025, so its first stored bar is the day its history begins.
NSDL = "INE301O01023"


@pytest.fixture(scope="module")
def seed(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        seeded_postgres, options=f"-csearch_path={FIXTURE_SCHEMA},public"
    ) as opened:
        yield opened


def committed_listings(connection: psycopg.Connection) -> set[tuple]:
    rows = connection.execute(
        "select isin, exchange, local_symbol, scrip_code, listing_date, delisting_date,"
        " closure_reason from listing"
    ).fetchall()
    return set(rows)


def derived_listings(connection: psycopg.Connection) -> set[tuple]:
    listings = close_listings(read_stretches(connection), venue_last_days(connection))
    return {
        (
            listing.isin,
            listing.exchange,
            listing.local_symbol,
            listing.scrip_code,
            listing.listing_date,
            listing.delisting_date,
            listing.closure_reason,
        )
        for listing in listings
    }


def test_the_stored_bars_reproduce_the_committed_listings(
    seed: psycopg.Connection,
) -> None:
    """The builder derived these from parsed files; the same answer has to come out of storage."""
    assert derived_listings(seed) == committed_listings(seed)


def test_a_change_of_isin_still_reads_as_superseded(seed: psycopg.Connection) -> None:
    derived = {row[:2]: row for row in derived_listings(seed)}

    assert derived[(BAJAJ_OLD, "BSE")][-1] == "superseded"
    assert derived[(BAJAJ_OLD, "NSE")][-1] == "superseded"


def test_the_stored_bars_reproduce_the_committed_successions(seed: psycopg.Connection) -> None:
    """Following the venue-local identifier out of storage has to reach the committed pairs."""
    derived = {
        (item.predecessor_isin, item.exchange, item.successor_isin, item.changed_on)
        for item in derive_successions(close_listings(read_stretches(seed), venue_last_days(seed)))
    }
    committed = set(
        seed.execute(
            "select predecessor_isin, exchange, successor_isin, changed_on"
            " from instrument_succession"
        ).fetchall()
    )

    assert derived == committed
    assert len(derived) == 6


def test_a_rename_keeps_both_names(seed: psycopg.Connection) -> None:
    """Eternal traded as Zomato at NSE, and grouping by ticker alone loses the earlier bars."""
    stretches = [stretch for stretch in read_stretches(seed) if stretch.isin == ETERNAL]
    nse = sorted(
        (stretch for stretch in stretches if stretch.exchange == "NSE"),
        key=lambda item: item.first_day,
    )

    assert [stretch.local_symbol for stretch in nse] == ["ZOMATO", "ETERNAL"]


def test_the_asset_writes_what_it_derives(
    seeded_postgres: str, migrated: Config, postgres_dsn: str
) -> None:
    """Run against a copy of the dataset, so the asset's own writes are what is read back."""
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        _copy_fixture_into(open_)

        result = instrument_identity(build_asset_context(), PointedDatabase(dsn=postgres_dsn))
        check = every_bar_sits_inside_a_listing(
            build_asset_context(), PointedDatabase(dsn=postgres_dsn)
        )
        linked = every_superseded_listing_names_its_successor(
            build_asset_context(), PointedDatabase(dsn=postgres_dsn)
        )

        stored = open_.execute("select count(*) from listing").fetchone()

        assert result.metadata["listings"] == (stored[0] if stored else 0)
        assert result.metadata["superseded"] == 6
        assert result.metadata["successions"] == 6
        assert check.passed
        assert check.metadata["bars_outside_a_listing"].value == 0
        assert linked.passed
        assert linked.metadata["superseded_without_a_successor"].value == 0

        open_.execute("delete from price_daily")
        open_.execute("delete from instrument_succession")
        open_.execute("delete from listing")
        open_.execute("delete from instrument_primary_venue")
        open_.execute("delete from instrument_master")
        open_.commit()


def test_a_stretch_reaching_an_earlier_first_day_leaves_no_row_behind(
    seeded_postgres: str, migrated: Config, postgres_dsn: str
) -> None:
    """A session held before an instrument's first stored day moves the day its stretch begins.

    BSE held a Muhurat session on Sunday 27 October 2019, two days before two instruments' first
    stored bar, and the stretch each began on the Tuesday stayed beside the one beginning Sunday.
    """
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        _copy_fixture_into(open_)
        instrument_identity(build_asset_context(), PointedDatabase(dsn=postgres_dsn))

        symbol, began = open_.execute(
            "select local_symbol, listing_date from listing where isin = %s and exchange = 'BSE'",
            (NSDL,),
        ).fetchone()
        isin = NSDL
        earlier = began - timedelta(days=2)
        columns = [
            row[0]
            for row in open_.execute(
                "select column_name from information_schema.columns"
                " where table_schema = %s and table_name = 'price_daily' order by ordinal_position",
                (MIGRATION_SCHEMA,),
            )
        ]
        listed = ", ".join(columns)
        shifted = ", ".join(
            "%s" if name in ("trade_date", "as_of_date") else name for name in columns
        )
        open_.execute(
            f"insert into price_daily ({listed}) select {shifted} from price_daily"
            " where isin = %s and venue = 'BSE' and trade_date = %s",
            (earlier, earlier, isin, began),
        )
        open_.commit()

        result = instrument_identity(build_asset_context(), PointedDatabase(dsn=postgres_dsn))
        check = every_bar_sits_inside_a_listing(
            build_asset_context(), PointedDatabase(dsn=postgres_dsn)
        )
        stretches = open_.execute(
            "select listing_date from listing"
            " where isin = %s and exchange = 'BSE' and local_symbol = %s",
            (isin, symbol),
        ).fetchall()

        assert result.metadata["retired"] == 1
        assert stretches == [(earlier,)]
        assert check.passed

        for table in (
            "price_daily",
            "instrument_succession",
            "listing",
            "instrument_primary_venue",
            "instrument_master",
        ):
            open_.execute(f"delete from {table}")
        open_.commit()


def test_a_derivation_that_loses_stretches_outright_is_refused(
    seeded_postgres: str, migrated: Config, postgres_dsn: str
) -> None:
    """A fault reading the history derives nothing, which reads the same as every stretch ending."""
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        _copy_fixture_into(open_)
        instrument_identity(build_asset_context(), PointedDatabase(dsn=postgres_dsn))

        with pytest.raises(StaleIdentity):
            retire_listings(open_, [])
        open_.rollback()

        stored = open_.execute("select count(*) from listing").fetchone()
        assert stored is not None and stored[0] > 0

        for table in (
            "price_daily",
            "instrument_succession",
            "listing",
            "instrument_primary_venue",
            "instrument_master",
        ):
            open_.execute(f"delete from {table}")
        open_.commit()


def _copy_fixture_into(connection: psycopg.Connection) -> None:
    """Move the committed instruments and bars across, leaving identity to be derived."""
    connection.execute(
        f"insert into instrument_master select * from {FIXTURE_SCHEMA}.instrument_master"
    )
    connection.execute(f"insert into price_daily select * from {FIXTURE_SCHEMA}.price_daily")
    connection.commit()
