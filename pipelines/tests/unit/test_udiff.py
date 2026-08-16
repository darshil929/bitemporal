"""The UDiFF parser reads both venues' recorded bhavcopies into canonical bars."""

import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pipelines.sources.bhavcopy import EQUITY_SERIES, normalize
from pipelines.sources.errors import SchemaDrift
from pipelines.sources.udiff import parse_udiff

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
TRADE_DATE = date(2026, 8, 14)


@pytest.fixture(scope="module")
def bse_payload() -> bytes:
    return (CASSETTES / "bse_bhavcopy_equity" / "20260814.csv").read_bytes()


@pytest.fixture(scope="module")
def nse_payload() -> bytes:
    archive = CASSETTES / "nse_bhavcopy_equity" / "20260814.csv.zip"
    with zipfile.ZipFile(archive) as opened:
        return opened.read(opened.namelist()[0])


def test_one_parser_reads_both_venues(bse_payload: bytes, nse_payload: bytes) -> None:
    """BSE and NSE publish the same columns, so the parser cannot be venue specific."""
    for payload in (bse_payload, nse_payload):
        rows = parse_udiff(payload)

        assert rows
        assert all(row.trade_date == TRADE_DATE for row in rows)
        assert all(len(row.isin) == 12 for row in rows)


def test_an_empty_optional_column_reads_as_none(nse_payload: bytes) -> None:
    rows = parse_udiff(nse_payload)

    assert any(row.turnover is not None for row in rows)
    assert all(row.previous_close is None or row.previous_close >= 0 for row in rows)


def test_a_response_missing_a_column_is_rejected() -> None:
    truncated = b"TradDt,ISIN,TckrSymb\n2026-08-14,INE002A01018,RELIANCE\n"

    with pytest.raises(SchemaDrift) as failure:
        parse_udiff(truncated)

    assert "ClsPric" in str(failure.value)


def test_an_empty_response_yields_no_rows() -> None:
    header = (CASSETTES / "bse_bhavcopy_equity" / "20260814.csv").read_bytes().split(b"\n")[0]

    assert parse_udiff(header + b"\n") == ()


@pytest.mark.parametrize("venue", ["BSE", "NSE"])
def test_normalize_keeps_only_equity_series(
    venue: str, bse_payload: bytes, nse_payload: bytes
) -> None:
    payload = bse_payload if venue == "BSE" else nse_payload
    rows = parse_udiff(payload)

    bars = normalize(rows, venue)

    kept_isins = {bar.isin for bar in bars}
    equity_isins = {row.isin for row in rows if row.series in EQUITY_SERIES[venue]}

    assert bars
    assert len(bars) < len(rows), "the recorded day carries non-equity series too"
    assert kept_isins == equity_isins


def test_government_securities_and_gold_bonds_are_excluded(nse_payload: bytes) -> None:
    """A bhavcopy carries bonds and government paper alongside equities."""
    rows = parse_udiff(nse_payload)
    excluded = {row.isin for row in rows if row.series in {"GS", "GB"}}

    bars = normalize(rows, "NSE")

    assert excluded, "the recorded day should contain government paper"
    assert excluded.isdisjoint({bar.isin for bar in bars})


def test_a_bar_carries_the_trade_date_as_its_as_of_date(bse_payload: bytes) -> None:
    """A bhavcopy is published the evening of the day it describes."""
    bars = normalize(parse_udiff(bse_payload), "BSE")

    assert all(bar.as_of_date == bar.trade_date for bar in bars)


def test_bse_bars_carry_a_scrip_code_and_nse_bars_do_not(
    bse_payload: bytes, nse_payload: bytes
) -> None:
    bse_bars = normalize(parse_udiff(bse_payload), "BSE")
    nse_bars = normalize(parse_udiff(nse_payload), "NSE")

    assert all(bar.scrip_code for bar in bse_bars)
    assert all(bar.scrip_code is None for bar in nse_bars)


def test_prices_survive_as_exact_decimals(bse_payload: bytes) -> None:
    """Rounding a paise-precision close through a float loses the published value."""
    bars = normalize(parse_udiff(bse_payload), "BSE")

    assert all(isinstance(bar.close, Decimal) for bar in bars)
    assert any(bar.close != bar.close.to_integral_value() for bar in bars)
