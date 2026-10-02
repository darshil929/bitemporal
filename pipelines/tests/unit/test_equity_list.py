"""Reading NSE's lists of equities for the main board and the SME platform."""

from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import SchemaDrift
from pipelines.sources.nse.bhavcopy import COOKIE_SOURCE_URL
from pipelines.sources.nse.equity_list import (
    SOURCE_ID,
    EquityListing,
    NseEquityList,
    names_by_isin,
    parse_listings,
)

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "nse_equity_list"
ARCHIVE = "https://nsearchives.nseindia.com"
READ_ON = date(2026, 10, 2)


def recorded(board: str) -> bytes:
    return (CASSETTES / f"{board}.csv").read_bytes()


def test_each_security_is_read_with_its_symbol_isin_and_name() -> None:
    listings = parse_listings(recorded("main"))

    assert len(listings) == 4
    assert (
        EquityListing(symbol="RELIANCE", isin="INE002A01018", name="Reliance Industries Limited")
        in listings
    )


def test_the_sme_list_is_read_whatever_its_column_names_join_with() -> None:
    """The SME list writes NAME_OF_COMPANY and ends each line with a comma."""
    assert parse_listings(recorded("sme")) == (
        EquityListing(symbol="POOJALOGIS", isin="INE1C2Q01017", name="Pooja Logistics Limited"),
    )


def test_spaces_inside_a_name_are_collapsed() -> None:
    names = names_by_isin(parse_listings(recorded("main")))
    assert names["INE171A01029"] == "The Federal Bank Limited"


def test_a_list_holding_its_header_alone_names_nothing() -> None:
    assert parse_listings(recorded("main").splitlines()[0] + b"\n") == ()


@pytest.mark.parametrize(
    "payload",
    [b"<html><body>Resource not found</body></html>", b"SYMBOL,NAME OF COMPANY,SERIES\nA,B,EQ\n"],
)
def test_an_answer_that_is_not_the_list_is_refused(payload: bytes) -> None:
    with pytest.raises(SchemaDrift):
        parse_listings(payload)


def adapter(cache: DiskCache) -> NseEquityList:
    return NseEquityList(ThrottledClient(SOURCE_ID, httpx.Client(), Throttle(0.0)), cache, ARCHIVE)


def test_each_board_is_asked_for_where_the_archive_host_serves_it() -> None:
    reader = adapter(None)  # type: ignore[arg-type]

    assert reader.url_for("main") == f"{ARCHIVE}/content/equities/EQUITY_L.csv"
    assert reader.url_for("sme") == f"{ARCHIVE}/emerge/corporates/content/SME_EQUITY_L.csv"


@respx.mock
def test_a_list_is_read_once_a_day_behind_the_session_cookie(tmp_path: Path) -> None:
    cookie = respx.get(COOKIE_SOURCE_URL).mock(return_value=httpx.Response(200))
    board = respx.get(url__startswith=ARCHIVE).mock(
        return_value=httpx.Response(200, content=recorded("sme"))
    )
    reader = adapter(DiskCache(tmp_path))

    assert reader.fetch("sme", READ_ON) == reader.fetch("sme", READ_ON) == recorded("sme")
    assert (cookie.call_count, board.call_count) == (1, 1)


@respx.mock
def test_an_answer_that_is_not_the_list_is_never_cached(tmp_path: Path) -> None:
    respx.get(COOKIE_SOURCE_URL).mock(return_value=httpx.Response(200))
    respx.get(url__startswith=ARCHIVE).mock(return_value=httpx.Response(200, content=b"<html>"))

    with pytest.raises(SchemaDrift):
        adapter(DiskCache(tmp_path)).fetch("main", READ_ON)

    assert not any(tmp_path.rglob("*.csv"))
