"""The legacy parsers read both venues' pre-cutover bhavcopies into the same canonical bars."""

import zipfile
from datetime import date
from pathlib import Path

import pytest

from pipelines.sources.bhavcopy import EQUITY_SERIES, normalize
from pipelines.sources.errors import MalformedRow, SchemaDrift, SourceError, WrongDay
from pipelines.sources.legacy import parse_bse_legacy, parse_nse_legacy

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
TRADE_DATE = date(2024, 1, 15)


def _only_csv(archive: Path) -> bytes:
    with zipfile.ZipFile(archive) as opened:
        return opened.read(opened.namelist()[0])


@pytest.fixture(scope="module")
def bse_payload() -> bytes:
    return _only_csv(CASSETTES / "bse_bhavcopy_equity" / "20240115_legacy.csv.zip")


@pytest.fixture(scope="module")
def nse_payload() -> bytes:
    return _only_csv(CASSETTES / "nse_bhavcopy_equity" / "20240115_legacy.csv.zip")


def test_the_bse_legacy_format_dates_rows_with_a_two_digit_year(bse_payload: bytes) -> None:
    """BSE writes 15-Jan-24 where NSE writes 15-JAN-2024."""
    rows = parse_bse_legacy(bse_payload)

    assert rows
    assert all(row.trade_date == TRADE_DATE for row in rows)


def test_the_nse_legacy_format_dates_rows_with_a_four_digit_year(nse_payload: bytes) -> None:
    rows = parse_nse_legacy(nse_payload)

    assert rows
    assert all(row.trade_date == TRADE_DATE for row in rows)


def test_both_legacy_formats_carry_an_isin(bse_payload: bytes, nse_payload: bytes) -> None:
    """Without ISIN a row cannot be joined to an instrument, whatever else it carries."""
    for rows in (parse_bse_legacy(bse_payload), parse_nse_legacy(nse_payload)):
        assert all(len(row.isin) == 12 for row in rows)


def test_bse_legacy_group_codes_arrive_padded(bse_payload: bytes) -> None:
    """The file pads SC_GROUP to a fixed width, so an unstripped value matches no series."""
    rows = parse_bse_legacy(bse_payload)

    assert all(row.series == row.series.strip() for row in rows)
    assert any(row.series in EQUITY_SERIES["BSE"] for row in rows)


@pytest.mark.parametrize("venue", ["BSE", "NSE"])
def test_legacy_rows_normalize_to_equity_bars(
    venue: str, bse_payload: bytes, nse_payload: bytes
) -> None:
    rows = parse_bse_legacy(bse_payload) if venue == "BSE" else parse_nse_legacy(nse_payload)

    bars = normalize(rows, venue)

    assert bars
    assert len(bars) < len(rows), "the recorded day carries non-equity series too"
    assert all(bar.venue == venue for bar in bars)
    assert all(bar.trade_date == TRADE_DATE for bar in bars)
    assert all(bar.as_of_date == bar.trade_date for bar in bars)


def test_treasury_bills_are_excluded_from_nse_bars(nse_payload: bytes) -> None:
    """The legacy NSE file carries treasury bills under series TB."""
    rows = parse_nse_legacy(nse_payload)
    bills = {row.isin for row in rows if row.series == "TB"}

    bars = normalize(rows, "NSE")

    assert bills, "the recorded day should contain treasury bills"
    assert bills.isdisjoint({bar.isin for bar in bars})


def test_bse_legacy_bars_keep_the_scrip_code(bse_payload: bytes) -> None:
    bars = normalize(parse_bse_legacy(bse_payload), "BSE")

    assert all(bar.scrip_code and bar.scrip_code.isdigit() for bar in bars)


def test_a_legacy_response_missing_a_column_is_rejected() -> None:
    truncated = b"SC_CODE,SC_NAME,OPEN\n500002,ABB,100\n"

    with pytest.raises(SchemaDrift) as failure:
        parse_bse_legacy(truncated)

    assert "ISIN_CODE" in str(failure.value)


BSE_HEADER = (
    "SC_CODE,SC_NAME,SC_GROUP,SC_TYPE,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,NO_TRADES,"
    "NO_OF_SHRS,NET_TURNOV,TDCLOINDI,ISIN_CODE,TRADING_DATE,FILLER2,FILLER3"
)

# BSE ran two records together on 2022-02-07, truncating an ISIN across the join, so a company
# name lands in the trade date column.
RAN_TOGETHER = (
    "531240,SHAMROCK IND,XT,Q,6.53,6.90,6.53,6.55,6.53,6.87,4,1060,6942.00,,INE540108,"
    "TIAANC      ,X ,Q,8.00,8.20,7.82,7.93,8.15,8.06,125,23356,16010.00,,INE802B01019,"
    "07-Feb-22,,"
)


def bse_line(scrip: int) -> str:
    return (
        f"{scrip},NAME {scrip}  ,A ,Q,2341.40,2347.05,2222.45,2258.45,2258.00,2331.70,"
        "1517,9702,21995538.00,,INE117A01022,07-Feb-22,,"
    )


def test_a_mangled_line_is_dropped_and_the_rest_of_the_day_survives() -> None:
    """A line the venue mangled is left out, and the rest of the day is read."""
    good = [bse_line(500000 + offset) for offset in range(200)]
    payload = "\n".join([BSE_HEADER, *good, RAN_TOGETHER]).encode()

    rows = parse_bse_legacy(payload)

    assert len(rows) == 200
    assert all(row.trade_date == date(2022, 2, 7) for row in rows)


def test_a_file_read_with_the_wrong_layout_is_refused() -> None:
    """Nearly every line failing means the parser is wrong about the file, not the venue."""
    payload = "\n".join([BSE_HEADER, bse_line(500002), RAN_TOGETHER, RAN_TOGETHER]).encode()

    with pytest.raises(MalformedRow) as raised:
        parse_bse_legacy(payload)

    assert "2 lines that are not bars" in str(raised.value)


def test_a_malformed_row_is_reported_as_a_source_failure() -> None:
    """A caller counts the day as failed and carries on, rather than the run ending."""
    assert issubclass(MalformedRow, SourceError)


# BSE published this header until 23 June 2017, and once afterwards on 14 December 2017. It is
# the dated layout with a filler standing where the trade date does now.
BSE_UNDATED_HEADER = BSE_HEADER.replace("TRADING_DATE", "FILLER1")


def undated_line(scrip: int) -> str:
    return bse_line(scrip).replace("07-Feb-22", "")


def test_a_file_without_a_trade_date_is_dated_from_the_day_it_was_asked_for() -> None:
    payload = f"{BSE_UNDATED_HEADER}\n{undated_line(500002)}".encode()

    rows = parse_bse_legacy(payload, date(2017, 3, 14))

    assert [row.trade_date for row in rows] == [date(2017, 3, 14)]


def test_a_file_without_a_trade_date_and_no_day_to_use_is_refused() -> None:
    """Nothing in the file says which day it describes, so it cannot be read on its own."""
    payload = f"{BSE_UNDATED_HEADER}\n{undated_line(500002)}".encode()

    with pytest.raises(SchemaDrift):
        parse_bse_legacy(payload)


def test_a_dated_file_keeps_the_date_it_carries() -> None:
    payload = f"{BSE_HEADER}\n{bse_line(500002)}".encode()

    rows = parse_bse_legacy(payload, date(2022, 2, 7))

    assert [row.trade_date for row in rows] == [date(2022, 2, 7)]


def test_a_file_describing_another_day_is_refused() -> None:
    """A dated file describes the day it was asked for, so one that does not is the wrong file."""
    payload = f"{BSE_HEADER}\n{bse_line(500002)}".encode()

    with pytest.raises(WrongDay):
        parse_bse_legacy(payload, date(2022, 2, 8))
