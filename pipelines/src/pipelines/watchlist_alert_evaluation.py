"""Watchlist alerts judged on every session their entry's venue published.

An alert is judged on each session that closed after it was set and before it ended: triggered when
its figure is past the threshold, watching when it is not or the session holds no such figure, and
paused when the instrument did not trade at that venue that day. Each verdict keeps the figure it
judged and the day that figure became known.
"""

from dataclasses import astuple, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import class_row

INDIA = ZoneInfo("Asia/Kolkata")
# Both venues close their equity sessions at 15:30 India time.
SESSION_CLOSE = time(15, 30)
PRICE_RULES = ("close_above", "close_below")

Spread = tuple[float | None, date]

BYPASSES_ROW_SECURITY = "select rolsuper or rolbypassrls from pg_roles where rolname = current_user"
ALERTS = """
select
    alerts.id, alerts.owner_id, alerts.rule, alerts.threshold, alerts.created_at, alerts.ended_at,
    entries.isin, entries.venue,
    (
        select max(verdicts.trade_date) from watchlist_alert_evaluation as verdicts
        where verdicts.alert_id = alerts.id
    ) as last_judged
from watchlist_alert as alerts
inner join watchlist_entry as entries on entries.id = alerts.entry_id
"""
SESSIONS = """
select venue, trade_date, as_of_date from mart_trading_days
where trade_date >= %(start)s and venue = any(%(venues)s)
"""
FIGURES = """
select isin, venue, trade_date, close, return_1d, delivery_pct_1d, as_of_date
from mart_venue_daily_figures
where trade_date >= %(start)s and isin = any(%(isins)s)
"""
# Read apart from the figures: joined to them, the grouped view is not narrowed to the instruments.
SPREADS = """
select isin, trade_date, venue_spread_bps, as_of_date from mart_venue_spread
where trade_date >= %(start)s and isin = any(%(isins)s)
"""
RECORD = """
insert into watchlist_alert_evaluation
    (owner_id, alert_id, trade_date, status, figure, as_of_date, paused_reason)
values (%s, %s, %s, %s, %s, %s, %s)
"""


class EvaluationRefused(Exception):
    """The connection's role is held by row security, so it would see no person's alerts."""


@dataclass(frozen=True)
class Alert:
    id: int
    owner_id: int
    rule: str
    threshold: Decimal
    created_at: datetime
    ended_at: datetime | None
    isin: str
    venue: str
    last_judged: date | None

    def judges(self, session_day: date) -> bool:
        """Whether the session of that day closed while the alert stood."""
        closed = datetime.combine(session_day, SESSION_CLOSE, INDIA)
        return self.created_at < closed and (self.ended_at is None or closed <= self.ended_at)

    def first_session(self) -> date:
        if self.last_judged is None:
            return self.created_at.astimezone(INDIA).date()
        return self.last_judged + timedelta(days=1)


@dataclass(frozen=True)
class Bar:
    close: Decimal
    return_1d: float | None
    delivery_pct_1d: float | None
    as_of_date: date


@dataclass(frozen=True)
class Verdict:
    status: str
    figure: float | None
    as_of_date: date
    paused_reason: str | None = None


@dataclass(frozen=True)
class Evaluated:
    judged: int
    triggered: int
    paused: int


def is_crossed(rule: str, figure: float, threshold: float) -> bool:
    if rule == "move_beyond":
        return abs(figure) > threshold
    if rule.endswith("_above"):
        return figure > threshold
    return figure < threshold


def judge(alert: Alert, session_as_of: date, bar: Bar | None, spread: Spread | None) -> Verdict:
    """The alert's verdict on one session, from the entry's bar at its venue that day."""
    if bar is None:
        return Verdict("paused", None, session_as_of, "not_traded")
    as_of_date = bar.as_of_date
    if alert.rule == "spread_above":
        figure = spread[0] if spread else None
        as_of_date = max(as_of_date, spread[1]) if spread else as_of_date
    elif alert.rule == "move_beyond":
        figure = bar.return_1d
    elif alert.rule in PRICE_RULES:
        figure = float(bar.close)
    else:
        figure = bar.delivery_pct_1d
    if figure is not None and is_crossed(alert.rule, figure, float(alert.threshold)):
        return Verdict("triggered", figure, as_of_date)
    return Verdict("watching", figure, as_of_date)


def evaluate_alerts(connection: psycopg.Connection) -> Evaluated:
    """Every alert judged on each session it stood through and has not been judged on."""
    bypasses = connection.execute(BYPASSES_ROW_SECURITY).fetchone()
    if bypasses is None or not bypasses[0]:
        raise EvaluationRefused("the role evaluating alerts must bypass row security")
    with connection.cursor(row_factory=class_row(Alert)) as cursor:
        alerts = cursor.execute(ALERTS).fetchall()
    if not alerts:
        return Evaluated(0, 0, 0)
    start = min(alert.first_session() for alert in alerts)
    isins = sorted({alert.isin for alert in alerts})

    sessions = connection.execute(
        SESSIONS, {"start": start, "venues": sorted({alert.venue for alert in alerts})}
    ).fetchall()
    bars = {
        (isin, venue, day): Bar(close, move, delivery, known)
        for isin, venue, day, close, move, delivery, known in connection.execute(
            FIGURES, {"start": start, "isins": isins}
        )
    }
    spread_isins = sorted({alert.isin for alert in alerts if alert.rule == "spread_above"})
    spreads = {
        (isin, day): (None if bps is None else float(bps), known)
        for isin, day, bps, known in connection.execute(
            SPREADS, {"start": start, "isins": spread_isins}
        )
    }

    records = []
    for alert in alerts:
        first = alert.first_session()
        for venue, day, session_as_of in sessions:
            if venue != alert.venue or day < first or not alert.judges(day):
                continue
            bar, spread = bars.get((alert.isin, venue, day)), spreads.get((alert.isin, day))
            verdict = judge(alert, session_as_of, bar, spread)
            records.append((alert.owner_id, alert.id, day, *astuple(verdict)))
    with connection.cursor() as cursor:
        cursor.executemany(RECORD, records)
    found = [record[3] for record in records]
    return Evaluated(len(found), found.count("triggered"), found.count("paused"))
