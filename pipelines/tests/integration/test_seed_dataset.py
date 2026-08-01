from collections.abc import Iterator

import psycopg
import pytest


@pytest.fixture(scope="module")
def connection(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(seeded_postgres) as conn:
        yield conn


def scalar(connection: psycopg.Connection, sql: str) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    assert row is not None
    return row[0]


def test_every_seed_table_is_populated(connection: psycopg.Connection) -> None:
    for table in ("instrument", "listing", "price_daily", "corporate_action"):
        assert scalar(connection, f"select count(*) from fixture.{table}") > 0


def test_dual_listed_instrument_has_diverging_venue_closes(
    connection: psycopg.Connection,
) -> None:
    spread = scalar(
        connection,
        """
        select max(abs(bse.close - nse.close))
        from fixture.price_daily as bse
        join fixture.price_daily as nse
            on bse.isin = nse.isin
            and bse.trade_date = nse.trade_date
        where bse.isin = 'INE100000001' and bse.venue = 'BSE' and nse.venue = 'NSE'
        """,
    )

    assert spread > 0


def test_bse_exclusive_instrument_trades_on_one_venue(connection: psycopg.Connection) -> None:
    venues = scalar(
        connection,
        "select count(distinct venue) from fixture.price_daily where isin = 'INE100000002'",
    )

    assert venues == 1


def test_split_and_bonus_are_present(connection: psycopg.Connection) -> None:
    actions = scalar(connection, "select count(distinct action_type) from fixture.corporate_action")

    assert actions == 2


def test_split_shows_as_an_unexplained_fall_in_raw_prices(
    connection: psycopg.Connection,
) -> None:
    ratio = scalar(
        connection,
        """
        select after.close / before.close
        from fixture.price_daily as before
        join fixture.price_daily as after
            on before.isin = after.isin and after.venue = before.venue
        where before.isin = 'INE100000003'
            and before.venue = 'BSE'
            and before.trade_date = date '2024-01-09'
            and after.trade_date = date '2024-01-10'
        """,
    )

    assert float(ratio) < 0.25


def test_suspended_instrument_stops_trading(connection: psycopg.Connection) -> None:
    last_traded = scalar(
        connection,
        "select max(trade_date) from fixture.price_daily where isin = 'INE100000005'",
    )
    latest = scalar(connection, "select max(trade_date) from fixture.price_daily")

    assert last_traded < latest


def test_delisted_instrument_carries_a_delisting_date(connection: psycopg.Connection) -> None:
    delisted = scalar(
        connection,
        "select count(*) from fixture.listing where delisting_date is not null",
    )

    assert delisted > 0


def test_symbol_change_adds_a_row_rather_than_overwriting(
    connection: psycopg.Connection,
) -> None:
    symbols = scalar(
        connection,
        "select count(distinct local_symbol) from fixture.listing where isin = 'INE100000007'",
    )

    assert symbols == 2


def test_instrument_listed_late_has_shorter_history(connection: psycopg.Connection) -> None:
    first_traded = scalar(
        connection,
        "select min(trade_date) from fixture.price_daily where isin = 'INE100000008'",
    )
    earliest = scalar(connection, "select min(trade_date) from fixture.price_daily")

    assert first_traded > earliest


def test_market_holiday_has_no_rows_for_any_instrument(connection: psycopg.Connection) -> None:
    rows = scalar(
        connection,
        "select count(*) from fixture.price_daily where trade_date = date '2024-01-04'",
    )

    assert rows == 0


def test_every_fact_row_carries_an_as_of_date(connection: psycopg.Connection) -> None:
    for table in ("price_daily", "corporate_action"):
        missing = scalar(
            connection, f"select count(*) from fixture.{table} where as_of_date is null"
        )
        assert missing == 0
