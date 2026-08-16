"""Adjustment checked against capital events the committed dataset actually contains.

An action removes a step from the price series. If the adjustment is right the step disappears:
the adjusted close of the last day before the ex-date sits within an ordinary day's movement of
the published close on the ex-date. If it is wrong the gap stays, and a momentum factor reads a
one for five split as an eighty percent fall.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from pipelines.adjustment import adjusted_close, factor_schedule
from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.models.market import PriceBar

FIXTURE_SCHEMA = "fixture"

RELIANCE = "INE002A01018"
SHRIRAM = "INE721A01047"
HDFC_BANK = "INE040A01034"
MAZAGON = "INE249Z01020"

# A day either side of a capital event still moves on its own account, so the join is asserted
# within an ordinary day's range rather than exactly.
ORDINARY_DAY = Decimal("0.08")


@pytest.fixture(scope="module")
def seed(seeded_postgres: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        seeded_postgres, options=f"-csearch_path={FIXTURE_SCHEMA},public"
    ) as opened:
        yield opened


@pytest.fixture(scope="module")
def actions(seed: psycopg.Connection) -> tuple[CorporateActionRecord, ...]:
    rows = seed.execute(
        "select isin, action_type, ex_date, source_id, as_of_date, qualifier,"
        " ratio_from, ratio_to, dividend_amount from corporate_action"
    ).fetchall()
    columns = [
        "isin",
        "action_type",
        "ex_date",
        "source_id",
        "as_of_date",
        "qualifier",
        "ratio_from",
        "ratio_to",
        "dividend_amount",
    ]
    return tuple(CorporateActionRecord(**dict(zip(columns, row, strict=True))) for row in rows)


def bars_around(
    connection: psycopg.Connection, isin: str, ex_date: date
) -> tuple[PriceBar, PriceBar]:
    """The last published bar before the ex-date, and the bar on it."""
    columns = [
        "isin",
        "venue",
        "trade_date",
        "as_of_date",
        "open",
        "high",
        "low",
        "close",
        "previous_close",
        "volume",
        "turnover",
        "trade_count",
    ]
    selection = (
        "select isin, venue, trade_date, as_of_date, open, high, low, close, previous_close,"
        " volume, turnover, trade_count from price_daily where isin = %s and venue = 'NSE'"
    )
    before = connection.execute(
        f"{selection} and trade_date < %s order by trade_date desc limit 1", (isin, ex_date)
    ).fetchone()
    on = connection.execute(f"{selection} and trade_date = %s", (isin, ex_date)).fetchone()

    assert before is not None and on is not None, f"{isin} has no bars around {ex_date}"
    return (
        PriceBar(**dict(zip(columns, before, strict=True)), local_symbol="", scrip_code=None),
        PriceBar(**dict(zip(columns, on, strict=True)), local_symbol="", scrip_code=None),
    )


@pytest.mark.parametrize(
    ("isin", "ex_date", "action_type", "expected_factor"),
    [
        (RELIANCE, date(2024, 10, 28), "bonus", Decimal("0.5")),
        (HDFC_BANK, date(2025, 8, 26), "bonus", Decimal("0.5")),
        (SHRIRAM, date(2025, 1, 10), "split", Decimal("0.2")),
        (MAZAGON, date(2024, 12, 27), "split", Decimal("0.5")),
    ],
)
def test_a_known_event_is_recorded_with_the_terms_the_price_implies(
    actions: tuple[CorporateActionRecord, ...],
    isin: str,
    ex_date: date,
    action_type: str,
    expected_factor: Decimal,
) -> None:
    recorded = [
        item
        for item in actions
        if item.isin == isin and item.ex_date == ex_date and item.action_type == action_type
    ]

    assert len(recorded) == 1, f"{isin} has no {action_type} on {ex_date}"
    assert recorded[0].ratio_from is not None and recorded[0].ratio_to is not None
    assert recorded[0].ratio_from / recorded[0].ratio_to == expected_factor


@pytest.mark.parametrize(
    ("isin", "ex_date"),
    [(RELIANCE, date(2024, 10, 28)), (HDFC_BANK, date(2025, 8, 26))],
)
def test_adjustment_closes_the_step_a_bonus_leaves(
    seed: psycopg.Connection,
    actions: tuple[CorporateActionRecord, ...],
    isin: str,
    ex_date: date,
) -> None:
    before, on = bars_around(seed, isin, ex_date)
    schedule = factor_schedule(actions)

    raw_step = before.close / on.close
    adjusted_step = adjusted_close(before, schedule) / on.close

    assert abs(raw_step - 1) > ORDINARY_DAY, "the published series should show a step here"
    assert abs(adjusted_step - 1) < ORDINARY_DAY, (
        f"{isin} still steps by {adjusted_step} after adjustment"
    )


def test_a_bar_after_every_action_is_left_at_its_published_price(
    seed: psycopg.Connection, actions: tuple[CorporateActionRecord, ...]
) -> None:
    _, on = bars_around(seed, RELIANCE, date(2024, 10, 28))
    schedule = factor_schedule(actions)

    assert adjusted_close(on, schedule) == on.close


@pytest.mark.parametrize(
    ("isin", "ex_date"), [(SHRIRAM, date(2025, 1, 10)), (MAZAGON, date(2024, 12, 27))]
)
def test_a_split_issues_a_new_isin_carrying_no_earlier_history(
    seed: psycopg.Connection, isin: str, ex_date: date
) -> None:
    """A face value change issues a new ISIN, so the split factor has nothing to apply to.

    The venue-local identifiers run through the change while the ISIN does not, which is what a
    continuous series across a split has to be rebuilt from.
    """
    first_day = seed.execute(
        "select min(trade_date) from price_daily where isin = %s", (isin,)
    ).fetchone()

    assert first_day is not None
    assert first_day[0] == ex_date


def test_an_instrument_with_no_capital_action_is_untouched(
    seed: psycopg.Connection, actions: tuple[CorporateActionRecord, ...]
) -> None:
    """Only actions changing the share count move a price; dividends are numerous and must not."""
    schedule = factor_schedule(actions)
    columns = [
        "isin",
        "venue",
        "trade_date",
        "as_of_date",
        "open",
        "high",
        "low",
        "close",
        "previous_close",
        "volume",
        "turnover",
        "trade_count",
    ]
    row = seed.execute(
        "select isin, venue, trade_date, as_of_date, open, high, low, close, previous_close,"
        " volume, turnover, trade_count from price_daily where isin = %s and venue = 'NSE'"
        " order by trade_date limit 1",
        ("INE009A01021",),
    ).fetchone()

    assert row is not None
    bar = PriceBar(**dict(zip(columns, row, strict=True)), local_symbol="", scrip_code=None)

    assert adjusted_close(bar, schedule) == bar.close
