"""Reading NSE corporate actions and turning their subject text into terms."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import SchemaDrift
from pipelines.sources.nse.corporate_actions import (
    FIRST_YEAR,
    NseCorporateActions,
    normalize,
    parse_actions,
    parse_subject,
    years,
)

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "nse_corporate_actions"
BASE = "https://www.nseindia.com/api"
COLLECTED_ON = date(2026, 9, 26)

SHRIRAM_OLD, SHRIRAM_NEW = "INE721A01013", "INE721A01047"
BAJAJ_2016, BAJAJ_NOW = "INE296A01016", "INE296A01032"
HDFC_2011, HDFC_NOW = "INE040A01018", "INE040A01034"
HCL, ITC = "INE860A01027", "INE154A01025"

# Each ISIN held, mapped to the one it trades under now.
ISIN_NOW = {
    SHRIRAM_OLD: SHRIRAM_NEW,
    SHRIRAM_NEW: SHRIRAM_NEW,
    BAJAJ_2016: BAJAJ_NOW,
    HDFC_2011: HDFC_NOW,
    HCL: HCL,
    ITC: ITC,
}


def recorded(year: int) -> bytes:
    return (CASSETTES / f"exdate-{year}0101-{year}1231.json").read_bytes()


def terms(subject: str) -> list[tuple[str, str, Decimal | None, Decimal | None, Decimal | None]]:
    return parse_subject(subject)


def test_a_bonus_is_shares_received_for_shares_held() -> None:
    """Bajaj Finance's four for one bonus of June 2025 took one share to five."""
    assert terms("Bonus 4:1") == [("bonus", "ordinary", Decimal(1), Decimal(5), None)]


def test_a_split_reads_its_terms_from_the_face_values() -> None:
    subject = "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"

    assert terms(subject) == [("split", "ordinary", Decimal(1), Decimal(5), None)]


def test_a_face_value_that_rises_is_a_consolidation() -> None:
    assert terms("Consolidation Of Shares From Re 1/- Per Share To Rs 10/- Per Share") == [
        ("consolidation", "ordinary", Decimal(10), Decimal(1), None)
    ]


def test_a_bonus_and_a_split_in_one_subject_are_both_read() -> None:
    """ONGC announced both in one subject in February 2011."""
    subject = "Bonus 1:1 And Face Value Split From Rs.10/- To Rs.5/-"

    assert [item[0] for item in terms(subject)] == ["bonus", "split"]


def test_a_bonus_of_debentures_issues_no_shares() -> None:
    subject = "Scheme Of Arrangement - Bonus Debentures 6:1"

    assert [item[0] for item in terms(subject)] == ["unhandled"]


def test_each_dividend_in_a_subject_keeps_its_kind() -> None:
    subject = "Interim Dividend - Rs 12 Per Share Special Dividend - Rs 6 Per Share"

    assert terms(subject) == [
        ("dividend", "interim", None, None, Decimal(12)),
        ("dividend", "special", None, None, Decimal(6)),
    ]


def test_older_wordings_of_a_dividend_are_read() -> None:
    assert terms("Interim Dividend-Rs.18/- Per Share")[0][4] == Decimal(18)
    assert terms("Interim Dividend Of Re.1/- Per Share")[0][4] == Decimal(1)


def test_a_dividend_stated_as_a_share_of_face_value_is_kept_as_text() -> None:
    assert terms("Dividend-50%") == [("unhandled", "dividend-50%", None, None, None)]


def test_a_dividend_left_unread_beside_a_bonus_is_kept_as_text() -> None:
    assert [item[0] for item in terms("Agm/ Div-100%/Bonus 1:1")] == ["bonus", "unhandled"]


def test_a_sub_division_is_not_mistaken_for_a_dividend() -> None:
    subject = "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share"

    assert [item[0] for item in terms(subject)] == ["split"]


def test_a_notice_of_a_meeting_announces_no_action() -> None:
    assert terms("Annual General Meeting") == []
    assert terms("-") == []


def test_an_action_without_derivable_terms_keeps_its_text() -> None:
    assert terms("Demerger") == [("unhandled", "demerger", None, None, None)]


def test_actions_are_recorded_under_the_isin_each_instrument_carries_now() -> None:
    """NSE filed Bajaj Finance's 2025 bonus and split under the ISIN it carried before 2016."""
    actions = normalize(parse_actions(recorded(2025)), ISIN_NOW, COLLECTED_ON)
    capital = {(item.isin, item.action_type, item.ex_date) for item in actions if item.ratio_from}

    assert capital == {
        (SHRIRAM_NEW, "split", date(2025, 1, 10)),
        (BAJAJ_NOW, "bonus", date(2025, 6, 16)),
        (BAJAJ_NOW, "split", date(2025, 6, 16)),
        (HDFC_NOW, "bonus", date(2025, 8, 26)),
    }
    assert all(item.as_of_date == COLLECTED_ON for item in actions)


def test_rows_outside_the_equity_series_are_left_out() -> None:
    """An InvIT's distribution is recorded in the IV series."""
    actions = normalize(parse_actions(recorded(2025)), ISIN_NOW, COLLECTED_ON)

    assert "INE0MIZ23019" not in {item.isin for item in actions}


def test_an_isin_outside_the_tracked_universe_is_left_out() -> None:
    actions = normalize(parse_actions(recorded(2011)), {}, COLLECTED_ON)

    assert actions == ()


def test_a_response_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(SchemaDrift):
        parse_actions(b'{"data": []}')


def test_the_years_run_from_1995_to_the_one_after_collection() -> None:
    walked = years(COLLECTED_ON)

    assert walked[0] == (date(FIRST_YEAR, 1, 1), date(FIRST_YEAR, 12, 31))
    assert walked[-1] == (date(2027, 1, 1), date(2027, 12, 31))


def test_a_range_is_asked_for_by_ex_date() -> None:
    adapter = NseCorporateActions(None, None, BASE)  # type: ignore[arg-type]

    url = adapter.url_for(date(2024, 10, 1), date(2024, 10, 31))

    assert url.endswith("index=equities&from_date=01-10-2024&to_date=31-10-2024")


@respx.mock
def test_an_answer_that_is_not_the_data_is_never_cached(tmp_path: Path) -> None:
    respx.get(url__startswith="https://www.nseindia.com/companies-listing").mock(
        return_value=httpx.Response(200)
    )
    respx.get(url__startswith=BASE).mock(return_value=httpx.Response(200, content=b"<html>"))
    cache = DiskCache(tmp_path)
    client = ThrottledClient("nse", httpx.Client(), Throttle(0.0), initial_backoff_seconds=0.001)
    adapter = NseCorporateActions(client, cache, BASE)

    with pytest.raises(SchemaDrift):
        adapter.fetch(date(2024, 1, 1), date(2024, 12, 31), COLLECTED_ON)

    assert not any(tmp_path.rglob("*.json"))
