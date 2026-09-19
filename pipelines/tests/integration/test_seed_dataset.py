"""The committed dataset holds every condition the later phases have to handle.

Each test names one condition. A future trim of the dataset that removes one fails here rather
than silently weakening whatever depends on it.
"""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

SCHEMA = "fixture"

# A split or a bonus shows as a fall the previous close does not explain.
ACTION_RATIO = 0.7


@pytest.fixture(scope="module")
def connection(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(seeded_postgres, options=f"-csearch_path={SCHEMA},public") as opened:
        yield opened


def scalar(connection: psycopg.Connection, sql: str, *parameters: Any) -> Any:
    row = connection.execute(sql, parameters or None).fetchone()
    assert row is not None
    return row[0]


def test_the_dataset_covers_two_years_of_both_venues(connection: psycopg.Connection) -> None:
    span = scalar(connection, "select max(trade_date) - min(trade_date) from price_daily")
    venues = scalar(connection, "select count(distinct venue) from price_daily")

    assert span > 600, "the window is shorter than the two years the factors need"
    assert venues == 2


def test_every_price_row_resolves_to_a_known_instrument(connection: psycopg.Connection) -> None:
    orphans = scalar(
        connection,
        "select count(*) from price_daily p"
        " left join instrument_master i on i.isin = p.isin where i.isin is null",
    )

    assert orphans == 0


def test_every_fact_row_carries_an_as_of_date(connection: psycopg.Connection) -> None:
    assert scalar(connection, "select count(*) from price_daily where as_of_date is null") == 0


def test_no_fact_is_knowable_before_the_period_it_describes(
    connection: psycopg.Connection,
) -> None:
    assert scalar(connection, "select count(*) from price_daily where as_of_date < trade_date") == 0


def test_a_capital_action_is_present(connection: psycopg.Connection) -> None:
    """Adjustment logic is meaningless without a real split or bonus to assert against."""
    worst = scalar(
        connection,
        "select min(close / previous_close) from price_daily"
        " where previous_close is not null and previous_close > 0",
    )

    assert worst is not None
    assert float(worst) < ACTION_RATIO


def test_an_instrument_changed_its_symbol(connection: psycopg.Connection) -> None:
    renamed = scalar(
        connection,
        "select count(*) from (select isin, exchange from listing"
        " group by isin, exchange having count(distinct local_symbol) > 1) as changed",
    )

    assert renamed > 0


def test_a_renamed_listing_says_why_it_closed(connection: psycopg.Connection) -> None:
    assert scalar(connection, "select count(*) from listing where closure_reason = 'renamed'") > 0


def test_an_instrument_stopped_trading(connection: psycopg.Connection) -> None:
    assert scalar(connection, "select count(*) from listing where closure_reason = 'delisted'") > 0


def test_both_sides_of_a_change_of_isin_are_present(connection: psycopg.Connection) -> None:
    """A series running across a split needs the predecessor and the successor, not one of them."""
    pairs = scalar(
        connection,
        "select count(*) from listing predecessor join listing successor"
        " on successor.exchange = predecessor.exchange"
        " and coalesce(successor.scrip_code, successor.local_symbol)"
        " = coalesce(predecessor.scrip_code, predecessor.local_symbol)"
        " and successor.isin <> predecessor.isin"
        " and successor.listing_date > predecessor.delisting_date"
        " where predecessor.closure_reason = 'superseded'",
    )

    assert pairs > 0


def test_each_superseded_listing_reaches_its_successor(connection: psycopg.Connection) -> None:
    """Both sides being present is not enough; the link between them has to be recorded."""
    superseded = scalar(
        connection, "select count(*) from listing where closure_reason = 'superseded'"
    )
    linked = scalar(
        connection,
        "select count(*) from listing l join instrument_succession s"
        " on s.predecessor_isin = l.isin and s.exchange = l.exchange"
        " join listing successor on successor.isin = s.successor_isin"
        " and successor.exchange = s.exchange and successor.listing_date = s.changed_on"
        " where l.closure_reason = 'superseded'",
    )

    assert superseded > 0
    assert linked == superseded


def test_an_action_without_derivable_terms_is_recorded(connection: psycopg.Connection) -> None:
    """A demerger stated only in free text must reach the database to mark the move it caused."""
    unhandled = scalar(
        connection,
        "select count(*) from corporate_action"
        " where action_type = 'unhandled' and purpose is not null and purpose <> ''",
    )
    inside_the_window = scalar(
        connection,
        "select count(*) from corporate_action where action_type = 'unhandled'"
        " and ex_date >= (select min(trade_date) from price_daily)",
    )

    assert unhandled > 0
    assert inside_the_window > 0


def test_no_action_is_knowable_before_it_happened(connection: psycopg.Connection) -> None:
    """The venue publishes no announcement date, so an action reads as known when collected."""
    ahead = scalar(connection, "select count(*) from corporate_action where ex_date > as_of_date")

    assert ahead == 0


def test_an_instrument_trades_on_bse_alone(connection: psycopg.Connection) -> None:
    bse_only = scalar(
        connection,
        "select count(*) from (select isin from price_daily"
        " group by isin having count(distinct venue) = 1"
        " and min(venue) = 'BSE') as single",
    )

    assert bse_only > 0


def test_a_dual_listed_instrument_closes_differently_on_each_venue(
    connection: psycopg.Connection,
) -> None:
    """Blending the two venues would produce a series matching no tradeable instrument."""
    divergent = scalar(
        connection,
        "select count(*) from ("
        " select isin, trade_date from price_daily"
        " group by isin, trade_date"
        " having count(distinct venue) = 2 and min(close) <> max(close)"
        ") as spread",
    )

    assert divergent > 0


def test_an_instrument_has_a_shorter_history_than_the_others(
    connection: psycopg.Connection,
) -> None:
    latest_start, earliest_start = connection.execute(
        "select max(started), min(started) from"
        " (select isin, min(trade_date) as started from price_daily group by isin) as starts"
    ).fetchone()  # type: ignore[misc]

    assert (latest_start - earliest_start).days > 200


def test_an_instrument_paused_and_resumed(connection: psycopg.Connection) -> None:
    """A suspension reads as a gap that the trading calendar does not explain."""
    longest_gap = scalar(
        connection,
        "select max(gap) from ("
        " select trade_date - lag(trade_date) over (partition by isin, venue order by trade_date)"
        " as gap from price_daily"
        ") as gaps",
    )

    assert longest_gap is not None
    assert longest_gap > 21


def test_a_market_holiday_falls_inside_the_window(connection: psycopg.Connection) -> None:
    """A weekday on which neither venue published is a holiday, not missing data."""
    weekdays = scalar(
        connection,
        "select count(*) from generate_series("
        " (select min(trade_date) from price_daily),"
        " (select max(trade_date) from price_daily), interval '1 day') as day"
        " where extract(isodow from day) < 6",
    )
    traded = scalar(connection, "select count(distinct trade_date) from price_daily")

    assert weekdays > traded


def test_every_traded_price_sits_inside_the_days_range(connection: psycopg.Connection) -> None:
    assert (
        scalar(
            connection,
            "select count(*) from price_daily where high < low or high < open or low > open",
        )
        == 0
    )
