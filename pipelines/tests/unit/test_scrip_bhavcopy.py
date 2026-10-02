"""BSE's scrip code bhavcopy, read on the days its ISIN file is not served whole."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import respx

from pipelines.sources.archive import extract_csv
from pipelines.sources.bhavcopy import normalize
from pipelines.sources.bse.bhavcopy import LEGACY, SCRIP, BseBhavcopy
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.legacy import named_by_isin, parse_bse_scrip
from pipelines.sources.registry import load_definitions

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "bse_bhavcopy_equity"
BSE_BASE = "https://www.bseindia.com/download/BhavCopy/Equity/"
SHORT_DAY = date(2022, 7, 15)


def scrip_payload() -> bytes:
    return extract_csv((CASSETTES / "20220715_scrip.zip").read_bytes())


def adapter(root: Path) -> BseBhavcopy:
    client = ThrottledClient("bse", httpx.Client(), Throttle(0.0), initial_backoff_seconds=0.001)
    return BseBhavcopy(client, DiskCache(root), BSE_BASE)


def test_the_registry_reads_the_scrip_code_file_on_the_days_bse_serves_no_whole_isin_file() -> None:
    bse = {item.source_id: item for item in load_definitions()}["bse_bhavcopy_equity"]

    read = {day: bse.version_for(day) for day in (date(2016, 12, 13), SHORT_DAY)}
    either_side = {
        bse.version_for(day)
        for day in (date(2016, 12, 12), date(2016, 12, 14), date(2022, 7, 14), date(2022, 7, 16))
    }

    assert set(read.values()) == {SCRIP}
    assert either_side == {LEGACY}


def test_the_scrip_code_file_follows_the_published_naming(tmp_path: Path) -> None:
    assert adapter(tmp_path).url_for(SHORT_DAY, SCRIP).endswith("Equity/EQ150722_CSV.ZIP")


def test_a_scrip_code_row_is_dated_from_the_request_and_names_no_isin() -> None:
    """A line is whole in the scrip code file where the ISIN file ran it into another."""
    rows = {row.scrip_code: row for row in parse_bse_scrip(scrip_payload(), SHORT_DAY)}

    assert {row.trade_date for row in rows.values()} == {SHORT_DAY}
    assert {row.isin for row in rows.values()} == {""}
    assert rows["531780"].turnover == Decimal("232308.00")


def test_a_row_takes_the_isin_its_scrip_code_resolves_to() -> None:
    """A code resolving to no ISIN is left blank, as a venue's own file marks a row naming nothing."""
    rows = named_by_isin(
        parse_bse_scrip(scrip_payload(), SHORT_DAY),
        {"531780": "INE229G01022", "541233": "INE970X01018", "541276": "INE626Z01011"},
    )

    bars = normalize(rows, "BSE")

    assert {(bar.scrip_code, bar.isin) for bar in bars} == {
        ("531780", "INE229G01022"),
        ("541233", "INE970X01018"),
        ("541269", ""),
        ("541276", "INE626Z01011"),
    }


@respx.mock
def test_the_scrip_code_file_is_cached_beside_the_isin_file_for_the_same_day(
    tmp_path: Path,
) -> None:
    """An ISIN file served with lines missing stays cached as served, beside the scrip code file."""
    isin_route = respx.get(BSE_BASE + "EQ_ISINCODE_150722.zip").mock(
        return_value=httpx.Response(
            200, content=(CASSETTES / "20220715_legacy_short.zip").read_bytes()
        )
    )
    scrip_route = respx.get(BSE_BASE + "EQ150722_CSV.ZIP").mock(
        return_value=httpx.Response(200, content=(CASSETTES / "20220715_scrip.zip").read_bytes())
    )
    bse = adapter(tmp_path)

    isin_file = bse.fetch(SHORT_DAY, LEGACY)
    scrip_file = bse.fetch(SHORT_DAY, SCRIP)

    assert scrip_file == scrip_payload()
    assert isin_file != scrip_file
    assert bse.fetch(SHORT_DAY, SCRIP) == scrip_file
    assert (isin_route.call_count, scrip_route.call_count) == (1, 1)
