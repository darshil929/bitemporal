"""The breadth, primary venue and venue figure marts the application reads beside the daily features."""

from collections import defaultdict
from datetime import date
from itertools import pairwise
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


def test_each_venue_s_figures_equal_the_features_on_its_primary_days(
    seeded_models: psycopg.Connection,
) -> None:
    compared, differing = seeded_models.execute(
        "select count(*), count(*) filter (where"
        " figures.isin is null"
        " or figures.change_1d is distinct from features.change_1d"
        " or figures.return_1d is distinct from features.return_1d"
        " or figures.return_1m is distinct from features.return_1m"
        " or figures.delivery_pct_1d is distinct from features.delivery_pct_1d)"
        " from mart_daily_features as features"
        " left join mart_venue_daily_figures as figures"
        " on figures.isin = features.isin and figures.venue = features.primary_venue"
        " and figures.trade_date = features.trade_date"
    ).fetchone() or (0, 0)

    assert compared > 0
    assert differing == 0


def test_the_other_venue_s_return_reads_its_own_previous_close(
    seeded_models: psycopg.Connection,
) -> None:
    closes: dict[tuple[str, str], list[tuple[date, float | None]]] = defaultdict(list)
    for isin, venue, day, close in seeded_models.execute(
        "select isin, venue, trade_date, close::float8 from mart_adjusted_prices"
        " order by isin, venue, trade_date"
    ):
        closes[(isin, venue)].append((day, close))
    expected = {
        (isin, venue, day): (close - previous) / previous
        for (isin, venue), series in closes.items()
        for (_, previous), (day, close) in pairwise(series)
        if close is not None and previous is not None
    }

    returns = {
        (isin, venue, day): return_1d
        for isin, venue, day, return_1d in seeded_models.execute(
            "select figures.isin, figures.venue, figures.trade_date, figures.return_1d"
            " from mart_venue_daily_figures as figures"
            " join mart_daily_features as features using (isin, trade_date)"
            " where figures.venue <> features.primary_venue and figures.return_1d is not null"
        )
    }

    assert returns
    assert returns == {key: expected[key] for key in returns}
