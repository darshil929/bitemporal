"""The legacy parsers read both venues' pre-cutover bhavcopies into the same canonical bars."""

import zipfile
from datetime import date
from pathlib import Path

import pytest

from pipelines.sources.bhavcopy import EQUITY_SERIES, normalize
from pipelines.sources.errors import SchemaDrift
from pipelines.sources.legacy import parse_bse_legacy, parse_nse_legacy

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
TRADE_DATE = date(2024, 1, 15)


@pytest.fixture(scope="module")
def bse_payload() -> bytes:
    return (CASSETTES / "bse_bhavcopy_equity" / "20240115_legacy.csv").read_bytes()


@pytest.fixture(scope="module")
def nse_payload() -> bytes:
    archive = CASSETTES / "nse_bhavcopy_equity" / "20240115_legacy.csv.zip"
    with zipfile.ZipFile(archive) as opened:
        return opened.read(opened.namelist()[0])


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
