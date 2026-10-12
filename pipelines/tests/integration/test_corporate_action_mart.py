"""The corporate actions the application lists, one row per action."""

from datetime import date
from decimal import Decimal

import psycopg

HDFC_BANK = "INE040A01034"
HDFC_BANK_BONUS = date(2025, 8, 26)


def test_a_bonus_both_venues_report_is_listed_once_with_its_terms(
    seeded_models: psycopg.Connection,
) -> None:
    listed = seeded_models.execute(
        "select reported_by, terms, adjustment_factor, is_applied from mart_corporate_actions"
        " where isin = %s and ex_date = %s and action_type = 'bonus'",
        (HDFC_BANK, HDFC_BANK_BONUS),
    ).fetchall()

    assert listed == [("both", "1 for 1", Decimal("0.500000"), True)]


def test_no_action_lists_both_venues_records(seeded_models: psycopg.Connection) -> None:
    doubled = seeded_models.execute(
        "select count(*) from (select isin, ex_date, action_type from mart_corporate_actions"
        " group by isin, ex_date, action_type having count(distinct source_id) > 1) as days"
    ).fetchone()
    reported_by_both = seeded_models.execute(
        "select count(*) from mart_corporate_actions where reported_by = 'both'"
    ).fetchone()

    assert doubled == (0,)
    assert reported_by_both is not None
    assert reported_by_both[0] > 0
