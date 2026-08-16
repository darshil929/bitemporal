"""Both venue adapters build their URL, cache the raw response and reuse it."""

from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import NotPublished
from pipelines.sources.nse.bhavcopy import COOKIE_SOURCE_URL, NseBhavcopy

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
PARTITION = date(2026, 8, 14)
BSE_BASE = "https://www.bseindia.com/download/BhavCopy/Equity/"
NSE_BASE = "https://nsearchives.nseindia.com/content/"


def build(source_id: str) -> ThrottledClient:
    return ThrottledClient(source_id, httpx.Client(), Throttle(0.0), initial_backoff_seconds=0.001)


def bse_bytes() -> bytes:
    return (CASSETTES / "bse_bhavcopy_equity" / "20260814.csv").read_bytes()


def nse_bytes() -> bytes:
    return (CASSETTES / "nse_bhavcopy_equity" / "20260814.csv.zip").read_bytes()


def test_the_bse_url_matches_the_published_naming() -> None:
    adapter = BseBhavcopy(build("bse"), DiskCache(Path()), BSE_BASE)

    assert adapter.url_for(PARTITION) == (
        "https://www.bseindia.com/download/BhavCopy/Equity/"
        "BhavCopy_BSE_CM_0_0_0_20260814_F_0000.CSV"
    )


def test_the_nse_url_matches_the_published_naming() -> None:
    adapter = NseBhavcopy(build("nse"), DiskCache(Path()), NSE_BASE)

    assert adapter.url_for(PARTITION) == (
        "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260814_F_0000.csv.zip"
    )


@respx.mock
def test_a_second_bse_fetch_reads_the_cache(tmp_path: Path) -> None:
    route = respx.get(url__startswith=BSE_BASE).mock(
        return_value=httpx.Response(200, content=bse_bytes())
    )
    adapter = BseBhavcopy(build("bse"), DiskCache(tmp_path), BSE_BASE)

    first = adapter.fetch(PARTITION)
    second = adapter.fetch(PARTITION)

    assert first == second
    assert route.call_count == 1


@respx.mock
def test_the_nse_adapter_collects_a_cookie_before_the_archive(tmp_path: Path) -> None:
    """The archive host drops a request carrying no cookie without answering."""
    cookie = respx.get(COOKIE_SOURCE_URL).mock(return_value=httpx.Response(200, content=b""))
    archive = respx.get(url__startswith=NSE_BASE).mock(
        return_value=httpx.Response(200, content=nse_bytes())
    )
    adapter = NseBhavcopy(build("nse"), DiskCache(tmp_path), NSE_BASE)

    adapter.fetch(PARTITION)

    assert cookie.call_count == 1
    assert archive.call_count == 1
    assert cookie.calls[0].request.url.host == "www.nseindia.com"


@respx.mock
def test_the_nse_adapter_unzips_what_the_venue_served(tmp_path: Path) -> None:
    respx.get(COOKIE_SOURCE_URL).mock(return_value=httpx.Response(200, content=b""))
    respx.get(url__startswith=NSE_BASE).mock(return_value=httpx.Response(200, content=nse_bytes()))
    cache = DiskCache(tmp_path)
    adapter = NseBhavcopy(build("nse"), cache, NSE_BASE)

    payload = adapter.fetch(PARTITION)

    assert payload.startswith(b"TradDt,BizDt")
    assert cache.read("nse_bhavcopy_equity", PARTITION.isoformat(), ".csv.zip") == nse_bytes()


@respx.mock
def test_a_holiday_is_reported_as_unpublished(tmp_path: Path) -> None:
    respx.get(url__startswith=BSE_BASE).mock(return_value=httpx.Response(404))
    adapter = BseBhavcopy(build("bse"), DiskCache(tmp_path), BSE_BASE)

    with pytest.raises(NotPublished):
        adapter.fetch(date(2026, 8, 15))


@respx.mock
def test_an_unpublished_day_is_not_cached(tmp_path: Path) -> None:
    """A holiday must not leave an entry that a later run mistakes for data."""
    respx.get(url__startswith=BSE_BASE).mock(return_value=httpx.Response(404))
    cache = DiskCache(tmp_path)
    adapter = BseBhavcopy(build("bse"), cache, BSE_BASE)

    with pytest.raises(NotPublished):
        adapter.fetch(date(2026, 8, 15))

    assert cache.read("bse_bhavcopy_equity", "2026-08-15", ".csv") is None


@respx.mock
def test_the_adapters_reach_canonical_bars_end_to_end(tmp_path: Path) -> None:
    respx.get(url__startswith=BSE_BASE).mock(return_value=httpx.Response(200, content=bse_bytes()))
    adapter = BseBhavcopy(build("bse"), DiskCache(tmp_path), BSE_BASE)

    bars = adapter.normalize(adapter.parse(adapter.fetch(PARTITION), "udiff"))

    assert bars
    assert all(bar.venue == "BSE" for bar in bars)
    assert all(bar.trade_date == PARTITION for bar in bars)
