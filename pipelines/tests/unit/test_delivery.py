"""Reading the delivery files both venues publish beside the bhavcopy."""

from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from pipelines.sources.bse.delivery import BseDelivery
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.delivery import (
    normalize,
    parse_bse_delivery,
    parse_nse_delivery,
    parse_nse_position,
)
from pipelines.sources.errors import NotPublished, SchemaDrift, WrongDay
from pipelines.sources.nse.delivery import POSITION, NseDelivery

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
PARTITION = date(2026, 8, 14)

NSE_BASE = "https://nsearchives.nseindia.com"
BSE_BASE = "https://www.bseindia.com/BSEDATA/gross"


def nse_bytes() -> bytes:
    return (CASSETTES / "nse_delivery" / "20260814.csv").read_bytes()


def bse_bytes() -> bytes:
    return (CASSETTES / "bse_delivery" / "20260814.zip").read_bytes()


def client(source_id: str) -> ThrottledClient:
    return ThrottledClient(source_id, httpx.Client(), Throttle(0.0), initial_backoff_seconds=0.001)


def test_the_nse_header_pads_every_name_with_a_space() -> None:
    """The file writes `SYMBOL, SERIES, DATE1`, so an unstripped name matches no column."""
    rows = parse_nse_delivery(nse_bytes())

    assert rows
    assert all(row.trade_date == PARTITION for row in rows)


def test_a_series_that_settles_nothing_is_left_out() -> None:
    """A non-deliverable series reports a dash, which is not a quantity of zero."""
    raw = nse_bytes().decode("utf-8")
    dashes = sum(1 for line in raw.splitlines()[1:] if line.split(",")[13].strip() == "-")
    rows = parse_nse_delivery(nse_bytes())

    assert dashes > 0, "the recorded day should carry a non-deliverable series"
    assert len(rows) == len(raw.splitlines()) - 1 - dashes


def test_the_bse_file_strips_the_padding_from_its_scrip_codes() -> None:
    rows = parse_bse_delivery(bse_bytes())

    assert rows
    assert all(not row.venue_key.startswith("0") for row in rows)
    assert all(row.trade_date == PARTITION for row in rows)


def test_bse_quantities_survive_their_zero_padding() -> None:
    """A quantity reads `0000000000023200`, which is twenty three thousand two hundred."""
    rows = parse_bse_delivery(bse_bytes())

    assert all(row.delivery_quantity >= 0 for row in rows)
    assert any(row.delivery_quantity > 0 for row in rows)


def test_a_response_missing_a_column_is_rejected() -> None:
    with pytest.raises(SchemaDrift):
        parse_nse_delivery(b"SYMBOL, SERIES\nRELIANCE, EQ\n")


def test_a_row_outside_the_tracked_universe_is_left_out() -> None:
    rows = parse_nse_delivery(nse_bytes())

    assert normalize(rows, "NSE", {}) == ()


def test_a_resolved_row_carries_its_trade_date_as_the_knowable_date(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The venue publishes delivery the same evening as the bar it belongs to."""
    rows = parse_nse_delivery(nse_bytes())
    resolved = normalize(rows, "NSE", {rows[0].venue_key: "INE002A01018"})

    assert len(resolved) == 1
    assert resolved[0].as_of_date == resolved[0].trade_date
    assert resolved[0].venue == "NSE"


def test_the_nse_url_matches_the_published_naming() -> None:
    adapter = NseDelivery(client("nse"), DiskCache(Path()), NSE_BASE)

    assert adapter.url_for(PARTITION).endswith("products/content/sec_bhavdata_full_14082026.csv")


def test_the_bse_url_files_the_archive_under_its_year() -> None:
    adapter = BseDelivery(client("bse"), DiskCache(Path()), BSE_BASE)

    assert adapter.url_for(PARTITION).endswith("gross/2026/SCBSEALL1408.zip")


@respx.mock
def test_a_second_bse_fetch_reads_the_cache(tmp_path: Path) -> None:
    route = respx.get(url__startswith=BSE_BASE).mock(
        return_value=httpx.Response(200, content=bse_bytes())
    )
    adapter = BseDelivery(client("bse"), DiskCache(tmp_path), BSE_BASE)

    assert adapter.fetch(PARTITION) == adapter.fetch(PARTITION)
    assert route.call_count == 1


@respx.mock
def test_a_bse_day_with_no_file_is_reported_as_unpublished(tmp_path: Path) -> None:
    """BSE answers with its home page and HTTP 200 for a date it holds nothing for."""
    respx.get(url__startswith=BSE_BASE).mock(
        return_value=httpx.Response(200, content=b"<!DOCTYPE html><html>")
    )
    cache = DiskCache(tmp_path)
    adapter = BseDelivery(client("bse"), cache, BSE_BASE)

    with pytest.raises(NotPublished):
        adapter.fetch(date(2026, 8, 15))

    assert cache.read("bse_delivery", "2026-08-15", ".zip") is None


def position_bytes(day: str) -> bytes:
    return (CASSETTES / "nse_delivery" / f"MTO_{day}.DAT").read_bytes()


def test_the_position_file_dates_every_row_from_its_header() -> None:
    """The file states its day once, above the rows, rather than on each of them."""
    rows = parse_nse_position(position_bytes("14082026"))

    assert {row.trade_date for row in rows} == {PARTITION}
    assert [row.venue_key for row in rows] == ["20MICRONS", "RELIANCE", "TCS"]


def test_the_position_file_carries_the_full_files_figures() -> None:
    """20MICRONS settled the same 109,556 shares on 14 August 2026 in both files NSE publishes."""
    position = {
        row.venue_key: row.delivery_quantity
        for row in parse_nse_position(position_bytes("14082026"))
    }
    full = {row.venue_key: row.delivery_quantity for row in parse_nse_delivery(nse_bytes())}

    assert position["20MICRONS"] == full["20MICRONS"] == 109_556


def test_the_position_url_matches_the_published_naming() -> None:
    adapter = NseDelivery(client("nse"), DiskCache(Path()), NSE_BASE)

    assert adapter.url_for(PARTITION, POSITION).endswith("archives/equities/mto/MTO_14082026.DAT")


@respx.mock
def test_a_file_describing_another_day_is_never_cached(tmp_path: Path) -> None:
    """NSE answers the address for 30 September 2019 with the file for 27 June.

    Held in the cache, that answer would be read back on every later run, and the day it was asked
    for could never be read again.
    """
    answered = (CASSETTES / "nse_delivery" / "20190930_describing_20190627.csv").read_bytes()
    respx.get(url__startswith="https://www.nseindia.com").mock(return_value=httpx.Response(200))
    respx.get(url__startswith=NSE_BASE).mock(return_value=httpx.Response(200, content=answered))
    cache = DiskCache(tmp_path)
    adapter = NseDelivery(client("nse"), cache, NSE_BASE)

    with pytest.raises(WrongDay):
        adapter.fetch(date(2019, 9, 30))

    assert cache.read("nse_delivery", "2019-09-30", ".csv") is None


def test_the_position_file_is_dated_from_its_control_record() -> None:
    """NSE headed the file for 30 March 2017 "rade Date", its control record naming the day intact."""
    rows = parse_nse_position(position_bytes("30032017"))

    assert {row.trade_date for row in rows} == {date(2017, 3, 30)}
    assert [row.venue_key for row in rows] == ["20MICRONS", "RELIANCE", "TCS"]
