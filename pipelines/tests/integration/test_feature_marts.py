"""The breadth and primary venue marts the application reads over the published daily features."""

from collections import defaultdict
from datetime import date
from statistics import median

import psycopg
import pytest

HDFC_BANK = "INE040A01034"


def test_breadth_counts_each_company_on_its_primary_venue(
    seeded_models: psycopg.Connection,
) -> None:
    returns: dict[date, list[float | None]] = defaultdict(list)
    highs: dict[date, int] = defaultdict(int)
    lows: dict[date, int] = defaultdict(int)
    for day, return_1d, is_high, is_low in seeded_models.execute(
        "select trade_date, return_1d, is_52w_high, is_52w_low from mart_daily_features"
        " where isin like 'INE%'"
    ):
        returns[day].append(return_1d)
        highs[day] += bool(is_high)
        lows[day] += bool(is_low)

    breadth = {
        day: rest
        for day, *rest in seeded_models.execute(
            "select trade_date, advancing, declining, unchanged, new_52w_highs, new_52w_lows,"
            " median_return_1d from mart_market_breadth"
        )
    }

    assert breadth
    assert sorted(breadth) == sorted(returns)
    for day, day_returns in returns.items():
        known = [value for value in day_returns if value is not None]
        advancing, declining, unchanged, new_highs, new_lows, median_return = breadth[day]
        assert (advancing, declining, unchanged) == (
            sum(value > 0 for value in known),
            sum(value < 0 for value in known),
            sum(value == 0 for value in known),
        )
        assert (new_highs, new_lows) == (highs[day], lows[day])
        assert median_return == (pytest.approx(median(known)) if known else None)


def test_a_day_is_complete_where_every_venue_in_session_completed_it(
    seeded_models: psycopg.Connection,
) -> None:
    verdicts: dict[date, bool] = {}
    for day, is_complete in seeded_models.execute(
        "select trade_date, is_complete from stg_trading_day"
    ):
        verdicts[day] = verdicts.get(day, True) and is_complete

    breadth = dict(seeded_models.execute("select trade_date, is_complete from mart_market_breadth"))

    assert breadth
    assert breadth == {day: verdicts[day] for day in breadth}


def test_each_instrument_opens_on_the_venue_of_its_newest_feature_row(
    seeded_models: psycopg.Connection,
) -> None:
    newest: dict[str, tuple[date, str]] = {}
    for isin, day, venue in seeded_models.execute(
        "select isin, trade_date, primary_venue from mart_daily_features"
    ):
        if isin not in newest or day > newest[isin][0]:
            newest[isin] = (day, venue)

    opened = {
        isin: (day, venue)
        for isin, day, venue in seeded_models.execute(
            "select isin, trade_date, primary_venue from mart_primary_venue"
        )
    }

    assert opened == newest
    assert opened[HDFC_BANK][1] == "NSE"
