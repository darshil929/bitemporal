"""Watchlist alerts judged against the seed dataset's published figures."""

import secrets
from collections.abc import Iterator
from datetime import date
from typing import Any

import psycopg
import pytest

from fixtures.database import SEED_SCHEMA
from pipelines.watchlist_alert_evaluation import EvaluationRefused, evaluate_alerts

HDFC_BANK = "INE040A01034"
BAJAJ_FINANCE_BEFORE_SPLIT = "INE296A01024"
SPICEJET_AT_BSE_ALONE = "INE285B01017"
# 27 Aug 2025 was a holiday at both venues.
LATE_AUGUST = ("2025-08-20 10:00+05:30", "2025-09-02 12:00+05:30")
AUGUST_SESSIONS = [date(2025, 8, day) for day in (20, 21, 22, 25, 26, 28, 29)] + [date(2025, 9, 1)]
# Every figure of the seed dataset became known on its last day.
KNOWN = "2025-12-31"
# Each stands through three sessions.
FROM_25_AUGUST = ("2025-08-25 09:00+05:30", "2025-08-29 09:00+05:30")
FROM_28_AUGUST = ("2025-08-28 09:00+05:30", "2025-09-02 15:00+05:30")
FROM_26_DECEMBER = ("2025-12-26 09:00+05:30", "2025-12-31 09:00+05:30")


@pytest.fixture
def connection(
    seeded_models: psycopg.Connection, seeded_postgres: str
) -> Iterator[psycopg.Connection]:
    """The seed dataset as the flows' role reaches it, every write rolled back after the test."""
    with psycopg.connect(seeded_postgres, options=f"-csearch_path={SEED_SCHEMA},public") as opened:
        yield opened
        opened.rollback()


def alert_on(
    connection: psycopg.Connection,
    isin: str,
    rule: str,
    threshold: float,
    stood: tuple[str, str],
    venue: str = "NSE",
) -> int:
    """An alert a new person set and ended at the moments `stood` names."""
    row = connection.execute(
        """
        with person as (
            insert into app_user (username, display_name, role, password_hash)
            values (%(username)s, 'Member', 'member', 'unused') returning id
        ), listed as (
            insert into watchlist (owner_id, name) select id, 'Watchlist' from person returning *
        ), entry as (
            insert into watchlist_entry (owner_id, watchlist_id, isin, venue, added_at)
            select owner_id, id, %(isin)s, %(venue)s, %(set)s from listed returning *
        )
        insert into watchlist_alert (owner_id, entry_id, rule, threshold, created_at, ended_at)
        select owner_id, id, %(rule)s, %(threshold)s, %(set)s, %(ended)s from entry returning id
        """,
        {
            "username": f"member-{secrets.token_hex(4)}",
            "isin": isin,
            "venue": venue,
            "rule": rule,
            "threshold": threshold,
            "set": stood[0],
            "ended": stood[1],
        },
    ).fetchone()
    assert row is not None
    return int(row[0])


def verdicts(connection: psycopg.Connection, alert: int) -> list[tuple[Any, ...]]:
    rows = connection.execute(
        "select trade_date, status, round(figure::numeric, 5)::float8, paused_reason"
        " from watchlist_alert_evaluation where alert_id = %s order by trade_date, as_of_date",
        (alert,),
    )
    return [tuple(row) for row in rows]


def judged_earlier(
    connection: psycopg.Connection,
    alert: int,
    day: str,
    as_of_date: str,
    status: str = "watching",
    paused_reason: str | None = None,
) -> None:
    connection.execute(
        "insert into watchlist_alert_evaluation"
        " (owner_id, alert_id, trade_date, as_of_date, status, paused_reason)"
        " select owner_id, id, %s, %s, %s, %s from watchlist_alert where id = %s",
        (day, as_of_date, status, paused_reason, alert),
    )


def test_an_alert_triggers_on_each_session_its_move_passes_the_threshold(
    connection: psycopg.Connection,
) -> None:
    moving = alert_on(connection, HDFC_BANK, "move_beyond", 0.012, LATE_AUGUST)

    evaluate_alerts(connection)

    judged = verdicts(connection, moving)
    assert [day for day, _, _, _ in judged] == AUGUST_SESSIONS
    assert [(day, figure) for day, status, figure, _ in judged if status == "triggered"] == [
        (date(2025, 8, 22), -0.01336),
        (date(2025, 8, 28), -0.01603),
    ]


@pytest.mark.parametrize(
    ("rule", "threshold", "stood", "venue", "expected"),
    [
        # 28 August closed at 957.80, at the limit and not past it.
        ("close_below", 957.8, FROM_28_AUGUST, "NSE", ["watching", "triggered", "triggered"]),
        ("delivery_above", 65, FROM_26_DECEMBER, "NSE", ["triggered", "watching", "triggered"]),
        ("spread_above", 3, FROM_25_AUGUST, "BSE", ["watching", "triggered", "watching"]),
    ],
)
def test_each_rule_compares_its_own_figure(
    connection: psycopg.Connection,
    rule: str,
    threshold: float,
    stood: tuple[str, str],
    venue: str,
    expected: list[str],
) -> None:
    alert = alert_on(connection, HDFC_BANK, rule, threshold, stood, venue)

    evaluate_alerts(connection)

    assert [status for _, status, _, _ in verdicts(connection, alert)] == expected


def test_an_alert_on_an_instrument_that_stopped_trading_pauses(
    connection: psycopg.Connection,
) -> None:
    replaced = alert_on(
        connection,
        BAJAJ_FINANCE_BEFORE_SPLIT,
        "move_beyond",
        0.02,
        ("2025-08-20 10:00+05:30", "2025-08-23 10:00+05:30"),
    )

    evaluate_alerts(connection)

    assert verdicts(connection, replaced) == [
        (day, "paused", None, "not_traded") for day in AUGUST_SESSIONS[:3]
    ]


def test_an_alert_on_a_replaced_isin_reads_its_sessions_until_the_change(
    connection: psycopg.Connection,
) -> None:
    replaced = alert_on(
        connection,
        BAJAJ_FINANCE_BEFORE_SPLIT,
        "move_beyond",
        0.02,
        ("2025-06-09 09:00+05:30", "2025-06-18 09:00+05:30"),
    )

    evaluate_alerts(connection)

    assert [
        (day.isoformat(), status, reason)
        for day, status, _, reason in verdicts(connection, replaced)
    ] == [
        ("2025-06-09", "triggered", None),
        ("2025-06-10", "watching", None),
        ("2025-06-11", "watching", None),
        ("2025-06-12", "watching", None),
        ("2025-06-13", "watching", None),
        ("2025-06-16", "paused", "not_traded"),
        ("2025-06-17", "paused", "not_traded"),
    ]


def test_a_session_holding_no_figure_for_the_rule_leaves_the_alert_watching(
    connection: psycopg.Connection,
) -> None:
    one_venue = alert_on(
        connection, SPICEJET_AT_BSE_ALONE, "spread_above", 3, FROM_25_AUGUST, "BSE"
    )

    evaluate_alerts(connection)

    judged = verdicts(connection, one_venue)
    assert len(judged) == 3
    assert {(status, figure) for _, status, figure, _ in judged} == {("watching", None)}


def test_a_session_is_judged_once(connection: psycopg.Connection) -> None:
    moving = alert_on(connection, HDFC_BANK, "move_beyond", 0.012, LATE_AUGUST)

    first = evaluate_alerts(connection)
    second = evaluate_alerts(connection)

    assert first.judged >= len(AUGUST_SESSIONS)
    assert second.judged == 0
    assert len(verdicts(connection, moving)) == len(AUGUST_SESSIONS)


def test_a_price_alert_pauses_once_a_capital_action_changes_the_price(
    connection: psycopg.Connection,
) -> None:
    set_before = alert_on(connection, HDFC_BANK, "close_below", 1500, LATE_AUGUST)
    set_after = alert_on(connection, HDFC_BANK, "close_below", 957.8, FROM_28_AUGUST)
    moving = alert_on(connection, HDFC_BANK, "move_beyond", 0.012, LATE_AUGUST)

    evaluate_alerts(connection)

    before = verdicts(connection, set_before)
    assert [status for _, status, _, _ in before[:4]] == ["watching"] * 4
    assert {(status, reason) for _, status, _, reason in before[4:]} == {
        ("paused", "capital_action")
    }
    assert "paused" not in [status for _, status, _, _ in verdicts(connection, set_after)]
    assert "paused" not in [status for _, status, _, _ in verdicts(connection, moving)]


def test_a_price_alert_stays_paused_long_after_the_capital_action(
    connection: psycopg.Connection,
) -> None:
    alert = alert_on(
        connection,
        HDFC_BANK,
        "close_below",
        1500,
        ("2025-08-20 10:00+05:30", "2025-10-02 12:00+05:30"),
    )
    judged_earlier(connection, alert, "2025-09-22", KNOWN, "paused", "capital_action")

    evaluate_alerts(connection)

    assert {(status, reason) for _, status, _, reason in verdicts(connection, alert)} == {
        ("paused", "capital_action")
    }


def test_a_session_within_the_correction_window_is_judged_again_under_its_later_date(
    connection: psycopg.Connection,
) -> None:
    moving = alert_on(connection, HDFC_BANK, "move_beyond", 0.012, LATE_AUGUST)
    judged_earlier(connection, moving, "2025-08-22", "2025-08-22")
    judged_earlier(connection, moving, "2025-08-28", "2025-08-28")
    judged_earlier(connection, moving, "2025-09-01", KNOWN)

    evaluate_alerts(connection)
    repeated = evaluate_alerts(connection)

    judged = verdicts(connection, moving)
    assert [status for day, status, _, _ in judged if day == date(2025, 8, 28)] == [
        "watching",
        "triggered",
    ]
    # 22 August moved past the threshold too, more than seven days before the last session judged.
    assert [status for day, status, _, _ in judged if day == date(2025, 8, 22)] == ["watching"]
    assert repeated.judged == 0


def test_a_role_held_by_row_security_judges_no_alert(connection: psycopg.Connection) -> None:
    alert_on(connection, HDFC_BANK, "move_beyond", 0.012, LATE_AUGUST)
    connection.execute("set role bitemporal_api")

    with pytest.raises(EvaluationRefused):
        evaluate_alerts(connection)
