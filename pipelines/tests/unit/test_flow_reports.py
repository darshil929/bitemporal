"""The days each flow reads, and the report a run of one prints."""

from datetime import date

import pytest
from dagster import AssetCheckEvaluation, AssetCheckSeverity, AssetKey

from pipelines.flows import ROWS_FOUND, FlowReport, bootstrap_windows, checks_by_outcome
from pipelines.jobs import sync_window

AGREEMENT = AssetKey("int_corporate_action_agreement")
ONE_SIDED = "assert_capital_actions_reported_by_both_venues"


def report(**changed: object) -> FlowReport:
    fields: dict[str, object] = {
        "first": date(2026, 9, 22),
        "last": date(2026, 9, 28),
        "counts": {
            "bse_bhavcopy": {
                "published": 5,
                "unpublished": 2,
                "outside_coverage": 0,
                "failed": 0,
                "rechecked": 2,
                "corrected": 1,
                "recheck_failed": 0,
            }
        },
        "failures": [],
        "checks_passed": 3,
        "warned_checks": [],
        "failed_checks": [],
        "failed_steps": [],
        "unmaterialized": [],
    }
    fields.update(changed)
    return FlowReport(**fields)  # type: ignore[arg-type]


def test_a_bootstrap_reads_the_two_most_recent_years_before_the_rest() -> None:
    assert bootstrap_windows(date(2026, 9, 28)) == [
        (date(2024, 9, 29), date(2026, 9, 28)),
        (date(2011, 6, 22), date(2024, 9, 28)),
    ]


def test_a_sync_reads_the_seven_days_ending_on_its_day() -> None:
    assert sync_window(date(2026, 9, 28)) == (date(2026, 9, 22), date(2026, 9, 28))


def test_a_run_that_read_every_source_is_clean() -> None:
    shown = report().lines()

    assert report().is_clean
    assert (
        "  bse_bhavcopy           published 5  unpublished 2  outside_coverage 0  failed 0"
        "  rechecked 2  corrected 1  recheck_failed 0" in shown
    )
    assert "  corporate_actions      not run" in shown


@pytest.mark.parametrize(
    ("changed", "line"),
    [
        (
            {"failures": [("bse_corporate_actions", "20260101-20261231", "refused with 403")]},
            "  failed bse_corporate_actions 20260101-20261231: refused with 403",
        ),
        (
            {"failed_checks": [("every_bar_sits_inside_a_listing", None)]},
            "  check failed: every_bar_sits_inside_a_listing",
        ),
        (
            {"failed_checks": [("assert_no_step_at_a_change_of_isin", 4)]},
            "  check failed: assert_no_step_at_a_change_of_isin, 4 rows",
        ),
        ({"failed_steps": ["instrument_identity"]}, "  step failed: instrument_identity"),
        ({"unmaterialized": ["bse_delivery"]}, "  not materialized: bse_delivery"),
    ],
)
def test_a_failure_of_any_kind_is_reported_and_fails_the_flow(
    changed: dict[str, object], line: str
) -> None:
    """A flow finishes whatever a source answers, so its report is what says a day went wrong."""
    failed = report(**changed)

    assert not failed.is_clean
    assert line in failed.lines()


def test_a_check_of_warning_severity_is_reported_and_fails_nothing() -> None:
    warned = report(checks_passed=121, warned_checks=[(ONE_SIDED, 17)])

    assert warned.is_clean
    assert "  checks 121 passed, 1 warned, 0 failed" in warned.lines()
    assert f"  check warned: {ONE_SIDED}, 17 rows" in warned.lines()


def test_checks_are_counted_by_their_outcome_and_severity() -> None:
    """dbt's warnings arrive as checks of warning severity that did not pass."""
    checks = [
        AssetCheckEvaluation(asset_key=AGREEMENT, check_name="not_null_isin", passed=True),
        AssetCheckEvaluation(
            asset_key=AGREEMENT,
            check_name=ONE_SIDED,
            passed=False,
            severity=AssetCheckSeverity.WARN,
            metadata={ROWS_FOUND: 17},
        ),
        AssetCheckEvaluation(
            asset_key=AGREEMENT, check_name="every_bar_sits_inside_a_listing", passed=False
        ),
    ]

    assert checks_by_outcome(checks) == (
        1,
        [(ONE_SIDED, 17)],
        [("every_bar_sits_inside_a_listing", None)],
    )
