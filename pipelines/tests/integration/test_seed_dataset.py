"""Assert the seed dataset contains the awkward cases downstream code has to survive.

Every assertion is a property of the dataset rather than a lookup of a known identifier, so
these hold against any dataset that satisfies the same requirements.
"""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest


@pytest.fixture(scope="module")
def connection(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(seeded_postgres) as conn:
        yield conn


def scalar(connection: psycopg.Connection, sql: str) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    assert row is not None
    return row[0]


def test_every_seed_table_is_populated(connection: psycopg.Connection) -> None:
    for table in ("instrument", "listing", "price_daily", "corporate_action"):
        assert scalar(connection, f"select count(*) from fixture.{table}") > 0


def test_every_priced_instrument_exists_in_the_master(connection: psycopg.Connection) -> None:
    orphans = scalar(
        connection,
        """
        select count(*)
        from fixture.price_daily as p
        left join fixture.instrument as i on i.isin = p.isin
        where i.isin is null
        """,
    )

    assert orphans == 0


def test_a_dual_listed_instrument_has_diverging_venue_closes(
    connection: psycopg.Connection,
) -> None:
    divergent = scalar(
        connection,
        """
        select count(*)
        from fixture.price_daily as a
        join fixture.price_daily as b
            on a.isin = b.isin and a.trade_date = b.trade_date and a.venue < b.venue
        where a.close <> b.close
        """,
    )

    assert divergent > 0


def test_an_instrument_trades_on_a_single_venue(connection: psycopg.Connection) -> None:
    single_venue = scalar(
        connection,
        """
        select count(*)
        from (
            select isin
            from fixture.price_daily
            group by isin
            having count(distinct venue) = 1
        ) as one_venue
        """,
    )

    assert single_venue > 0


def test_both_a_split_and_a_bonus_are_present(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("select distinct action_type from fixture.corporate_action")
        action_types = {row[0] for row in cursor.fetchall()}

    assert {"split", "bonus"} <= action_types


def test_every_corporate_action_looks_like_a_crash_in_raw_prices(
    connection: psycopg.Connection,
) -> None:
    """Raw prices are never adjusted, so an action must show as a large unexplained fall.

    This is the failure the fixture exists to catch: a split that nothing flags reads as a
    collapse, momentum factors fire on it, and no error is raised anywhere.
    """
    worst_ratio = scalar(
        connection,
        """
        with priced as (
            select
                isin,
                venue,
                trade_date,
                close,
                lag(close) over (partition by isin, venue order by trade_date) as previous_close
            from fixture.price_daily
        )
        select max(p.close / p.previous_close)
        from fixture.corporate_action as a
        join priced as p on p.isin = a.isin and p.trade_date = a.ex_date
        where p.previous_close is not null
        """,
    )

    assert worst_ratio is not None, "no corporate action lines up with a priced trading day"
    assert float(worst_ratio) < 0.7


def test_an_instrument_stops_trading_without_being_delisted(
    connection: psycopg.Connection,
) -> None:
    suspended = scalar(
        connection,
        """
        select count(*)
        from (
            select p.isin
            from fixture.price_daily as p
            join fixture.listing as l on l.isin = p.isin
            group by p.isin
            having max(p.trade_date) < (select max(trade_date) from fixture.price_daily)
                and bool_and(l.delisting_date is null)
        ) as suspended
        """,
    )

    assert suspended > 0


def test_a_delisted_instrument_has_no_prices_after_its_delisting_date(
    connection: psycopg.Connection,
) -> None:
    # Only the most recent listing row per venue says whether an instrument still trades. An
    # older closed row means the symbol was superseded by a rename, not that it was delisted.
    latest_listing = """
        select distinct on (isin, exchange) isin, exchange, delisting_date
        from fixture.listing
        order by isin, exchange, listing_date desc
    """

    delisted = scalar(
        connection,
        f"select count(*) from ({latest_listing}) as l where l.delisting_date is not null",
    )
    prices_after_delisting = scalar(
        connection,
        f"""
        select count(*)
        from fixture.price_daily as p
        join ({latest_listing}) as l on l.isin = p.isin and l.exchange = p.venue
        where l.delisting_date is not null and p.trade_date > l.delisting_date
        """,
    )

    assert delisted > 0
    assert prices_after_delisting == 0


def test_a_symbol_change_adds_a_listing_row_rather_than_overwriting(
    connection: psycopg.Connection,
) -> None:
    renamed = scalar(
        connection,
        """
        select count(*)
        from (
            select isin, exchange
            from fixture.listing
            group by isin, exchange
            having count(distinct local_symbol) > 1
        ) as renamed
        """,
    )

    assert renamed > 0


def test_an_instrument_has_a_shorter_history_than_the_others(
    connection: psycopg.Connection,
) -> None:
    late_listings = scalar(
        connection,
        """
        select count(*)
        from (
            select isin
            from fixture.price_daily
            group by isin
            having min(trade_date) > (select min(trade_date) from fixture.price_daily)
        ) as late
        """,
    )

    assert late_listings > 0


def test_a_weekday_inside_the_range_has_no_trading_at_all(
    connection: psycopg.Connection,
) -> None:
    holidays = scalar(
        connection,
        """
        select count(*)
        from generate_series(
            (select min(trade_date) from fixture.price_daily),
            (select max(trade_date) from fixture.price_daily),
            interval '1 day'
        ) as calendar (day)
        where extract(isodow from calendar.day) <= 5
            and not exists (
                select 1 from fixture.price_daily where trade_date = calendar.day::date
            )
        """,
    )

    assert holidays > 0


def test_every_fact_row_carries_an_as_of_date(connection: psycopg.Connection) -> None:
    for table in ("price_daily", "corporate_action"):
        missing = scalar(
            connection, f"select count(*) from fixture.{table} where as_of_date is null"
        )
        assert missing == 0


def test_no_fact_is_knowable_before_the_period_it_describes(
    connection: psycopg.Connection,
) -> None:
    early = scalar(
        connection,
        "select count(*) from fixture.price_daily where as_of_date < trade_date",
    )

    assert early == 0
