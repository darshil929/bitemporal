"""Adjustment factors rebuilt from the whole action history."""

from datetime import date
from decimal import Decimal

from pipelines.adjustment import adjust, factor_for, factor_schedule
from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.models.market import PriceBar

RELIANCE = "INE002A01018"
REPORTED_ON = date(2026, 8, 16)


def action(
    action_type: str = "split",
    ex_date: str = "2025-01-10",
    ratio_from: str = "1",
    ratio_to: str = "5",
    as_of: str = "2026-08-16",
    dividend: str | None = None,
) -> CorporateActionRecord:
    return CorporateActionRecord(
        isin=RELIANCE,
        action_type=action_type,
        ex_date=date.fromisoformat(ex_date),
        source_id="bse_corporate_actions",
        as_of_date=date.fromisoformat(as_of),
        ratio_from=None if dividend else Decimal(ratio_from),
        ratio_to=None if dividend else Decimal(ratio_to),
        dividend_amount=Decimal(dividend) if dividend else None,
    )


def bar(day: str, close: str) -> PriceBar:
    return PriceBar(
        isin=RELIANCE,
        venue="NSE",
        trade_date=date.fromisoformat(day),
        as_of_date=date.fromisoformat(day),
        local_symbol="RELIANCE",
        scrip_code=None,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        previous_close=None,
        volume=1,
        turnover=Decimal(1),
        trade_count=1,
    )


def test_a_bar_before_a_five_way_split_is_scaled_to_a_fifth() -> None:
    schedule = factor_schedule([action()])

    assert factor_for(schedule[RELIANCE], date(2025, 1, 9)) == Decimal("0.2")


def test_a_bar_on_the_ex_date_is_left_alone() -> None:
    """The published price already reflects the action from the ex-date onward."""
    schedule = factor_schedule([action()])

    assert factor_for(schedule[RELIANCE], date(2025, 1, 10)) == Decimal(1)


def test_a_one_for_one_bonus_halves_earlier_prices() -> None:
    schedule = factor_schedule([action("bonus", "2024-10-28", "1", "2")])

    assert factor_for(schedule[RELIANCE], date(2024, 10, 25)) == Decimal("0.5")


def test_two_actions_compound_for_a_bar_that_precedes_both() -> None:
    """A bar before a bonus and a split carries the product of the two, not the nearer one."""
    schedule = factor_schedule(
        [action("bonus", "2024-10-28", "1", "2"), action("split", "2025-01-10", "1", "5")]
    )[RELIANCE]

    assert factor_for(schedule, date(2024, 10, 1)) == Decimal("0.1")
    assert factor_for(schedule, date(2024, 12, 1)) == Decimal("0.2")
    assert factor_for(schedule, date(2025, 2, 1)) == Decimal(1)


def test_a_consolidation_raises_earlier_prices() -> None:
    schedule = factor_schedule([action("consolidation", "2025-01-10", "10", "1")])

    assert factor_for(schedule[RELIANCE], date(2025, 1, 9)) == Decimal(10)


def test_a_dividend_leaves_the_price_series_alone() -> None:
    """Adjusting for a dividend would produce a total return series, which is a different thing."""
    assert factor_schedule([action(dividend="10.00", action_type="dividend")]) == {}


def test_an_action_added_later_corrects_every_earlier_bar() -> None:
    """Factors are rebuilt from the whole history, so a late arrival leaves no step behind."""
    before = adjust([bar("2024-10-01", "2800")], [action("bonus", "2024-10-28", "1", "2")])
    after = adjust(
        [bar("2024-10-01", "2800")],
        [action("bonus", "2024-10-28", "1", "2"), action("split", "2025-01-10", "1", "5")],
    )

    assert before[(RELIANCE, "NSE", date(2024, 10, 1))] == Decimal("1400.0000")
    assert after[(RELIANCE, "NSE", date(2024, 10, 1))] == Decimal("280.0000")


def test_a_restated_action_uses_the_version_reported_last() -> None:
    schedule = factor_schedule(
        [
            action("split", "2025-01-10", "1", "2", as_of="2025-01-05"),
            action("split", "2025-01-10", "1", "5", as_of="2025-01-09"),
        ]
    )

    assert factor_for(schedule[RELIANCE], date(2025, 1, 9)) == Decimal("0.2")


def test_an_instrument_with_no_actions_is_unchanged() -> None:
    adjusted = adjust([bar("2025-06-02", "1234.5600")], [])

    assert adjusted[(RELIANCE, "NSE", date(2025, 6, 2))] == Decimal("1234.5600")
