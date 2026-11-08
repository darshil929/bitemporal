from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from api.services.attention_feed import MarketFacts, attention
from api.services.watchlist_daily_reads import Verdict
from api.services.watchlist_management import Alert, Entry

DAY = date(2026, 11, 6)
SET = datetime(2026, 11, 2, tzinfo=UTC)
HDFC_BANK, INFOSYS, RPSG = "INE040A01034", "INE009A01021", "INE425Y01011"
BAJAJ_BEFORE_SPLIT, BAJAJ = "INE296A01024", "INE296A01032"


def entry(entry_id: int, isin: str, watchlist_id: int = 1, alert: int | None = None) -> Entry:
    rule = Alert(alert, "move_beyond", Decimal("0.02"), SET) if alert else None
    return Entry(entry_id, watchlist_id, isin, "NSE", SET, rule)


def facts(**known: object) -> MarketFacts:
    identities = {
        isin: SimpleNamespace(display_name=isin.lower(), current_isin=current)
        for isin, current in [
            (HDFC_BANK, HDFC_BANK),
            (INFOSYS, INFOSYS),
            (BAJAJ_BEFORE_SPLIT, BAJAJ),
        ]
    }
    defaults: dict[str, object] = {
        "published_day": DAY,
        "identities": identities,
        "venue_sessions": {"NSE": DAY, "BSE": DAY},
        "incomplete": [],
        "diverging": {},
        "unhandled": [],
    }
    return MarketFacts(**(defaults | known))  # type: ignore[arg-type]


def test_an_alert_the_newest_session_triggered_is_listed_alone() -> None:
    entries = (
        entry(1, HDFC_BANK, alert=11),
        entry(2, INFOSYS, alert=12),
        entry(3, HDFC_BANK, 2, 13),
    )
    verdicts = {
        11: Verdict(DAY, "triggered", -0.023, None),
        12: Verdict(DAY, "watching", 0.004, None),
        13: Verdict(date(2026, 11, 5), "triggered", 0.031, None),
    }

    found = attention(entries, verdicts, facts())

    assert [(alert.entry_id, alert.figure, alert.trade_date) for alert in found.alerts] == [
        (1, -0.023, DAY)
    ]


def test_a_held_instrument_is_listed_once_and_an_unheld_one_not_at_all() -> None:
    entries = (entry(1, HDFC_BANK), entry(2, HDFC_BANK, watchlist_id=2))
    unhandled = [
        SimpleNamespace(
            isin=HDFC_BANK, ex_date=date(2026, 10, 20), purpose="Scheme of Arrangement"
        ),
        SimpleNamespace(isin=INFOSYS, ex_date=date(2026, 10, 21), purpose="Buy Back of Shares"),
    ]

    found = attention(
        entries, {}, facts(diverging={HDFC_BANK: 612.0, RPSG: 658.0}, unhandled=unhandled)
    )

    assert [(item.isin, item.venue_spread_bps) for item in found.divergences] == [
        (HDFC_BANK, 612.0)
    ]
    assert [(item.isin, item.purpose) for item in found.unhandled_actions] == [
        (HDFC_BANK, "Scheme of Arrangement")
    ]


def test_each_venue_whose_published_session_failed_its_checks_is_listed() -> None:
    incomplete = [
        SimpleNamespace(venue="BSE", divergent_instruments=1, detail="1 instruments diverge")
    ]

    found = attention((), {}, facts(incomplete=incomplete))

    assert [(item.venue, item.trade_date) for item in found.incomplete_sessions] == [("BSE", DAY)]


def test_a_replaced_isin_is_listed_once_with_its_successor() -> None:
    entries = (entry(1, BAJAJ_BEFORE_SPLIT), entry(2, BAJAJ_BEFORE_SPLIT, watchlist_id=2))

    found = attention(entries, {}, facts())

    assert [(item.isin, item.superseded_by) for item in found.superseded] == [
        (BAJAJ_BEFORE_SPLIT, BAJAJ)
    ]


def test_nothing_needs_attention_on_a_quiet_day() -> None:
    found = attention((entry(1, HDFC_BANK, alert=11),), {}, facts())

    assert (found.alerts, found.incomplete_sessions, found.divergences) == ((), (), ())
    assert (found.superseded, found.unhandled_actions) == ((), ())
