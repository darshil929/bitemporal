"""The registered schema version drives both the url an adapter builds and the parser it uses."""

import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import UnknownSchemaVersion
from pipelines.sources.legacy import BseLegacyRow, NseLegacyRow
from pipelines.sources.nse.bhavcopy import COOKIE_SOURCE_URL, NseBhavcopy
from pipelines.sources.registry import load_definitions
from pipelines.sources.udiff import UdiffRow

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
BSE_BASE = "https://www.bseindia.com/download/BhavCopy/Equity/"
NSE_BASE = "https://nsearchives.nseindia.com/content/"

LAST_LEGACY_DAY = date(2024, 7, 5)
FIRST_UDIFF_DAY = date(2024, 7, 8)


def client(source_id: str) -> ThrottledClient:
    return ThrottledClient(source_id, httpx.Client(), Throttle(0.0), initial_backoff_seconds=0.001)


def bse_adapter(root: Path) -> BseBhavcopy:
    return BseBhavcopy(client("bse"), DiskCache(root), BSE_BASE)


def nse_adapter(root: Path) -> NseBhavcopy:
    return NseBhavcopy(client("nse"), DiskCache(root), NSE_BASE)


def version_for(source_id: str, partition: date) -> str:
    definitions = {item.source_id: item for item in load_definitions()}
    return definitions[source_id].version_for(partition)


def test_the_registry_selects_a_different_parser_either_side_of_the_cutover() -> None:
    for source_id in ("bse_bhavcopy_equity", "nse_bhavcopy_equity"):
        assert version_for(source_id, FIRST_UDIFF_DAY) == "udiff"
        assert version_for(source_id, LAST_LEGACY_DAY) != "udiff"


def test_the_bse_url_follows_the_version(tmp_path: Path) -> None:
    adapter = bse_adapter(tmp_path)

    assert adapter.url_for(FIRST_UDIFF_DAY, "udiff").endswith(
        "BhavCopy_BSE_CM_0_0_0_20240708_F_0000.CSV"
    )
    assert adapter.url_for(LAST_LEGACY_DAY, "bse_legacy").endswith("EQ_ISINCODE_050724.CSV")


def test_the_nse_url_follows_the_version(tmp_path: Path) -> None:
    adapter = nse_adapter(tmp_path)

    assert adapter.url_for(FIRST_UDIFF_DAY, "udiff").endswith(
        "cm/BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip"
    )
    assert adapter.url_for(LAST_LEGACY_DAY, "nse_legacy").endswith(
        "historical/EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip"
    )


def test_each_version_produces_its_own_row_type(tmp_path: Path) -> None:
    bse = bse_adapter(tmp_path)
    nse = nse_adapter(tmp_path)
    udiff_payload = (CASSETTES / "bse_bhavcopy_equity" / "20260814.csv").read_bytes()
    legacy_payload = (CASSETTES / "bse_bhavcopy_equity" / "20240115_legacy.csv").read_bytes()

    with zipfile.ZipFile(CASSETTES / "nse_bhavcopy_equity" / "20240115_legacy.csv.zip") as archive:
        nse_legacy_payload = archive.read(archive.namelist()[0])

    assert isinstance(bse.parse(udiff_payload, "udiff")[0], UdiffRow)
    assert isinstance(bse.parse(legacy_payload, "bse_legacy")[0], BseLegacyRow)
    assert isinstance(nse.parse(nse_legacy_payload, "nse_legacy")[0], NseLegacyRow)


def test_an_unregistered_version_is_refused(tmp_path: Path) -> None:
    adapter = bse_adapter(tmp_path)

    with pytest.raises(UnknownSchemaVersion):
        adapter.url_for(FIRST_UDIFF_DAY, "guessed")

    with pytest.raises(UnknownSchemaVersion):
        adapter.parse(b"", "guessed")


@respx.mock
def test_a_legacy_day_reaches_canonical_bars_end_to_end(tmp_path: Path) -> None:
    with zipfile.ZipFile(CASSETTES / "nse_bhavcopy_equity" / "20240115_legacy.csv.zip") as archive:
        payload = (CASSETTES / "nse_bhavcopy_equity" / "20240115_legacy.csv.zip").read_bytes()
        assert archive.namelist()

    respx.get(COOKIE_SOURCE_URL).mock(return_value=httpx.Response(200, content=b""))
    respx.get(url__startswith=NSE_BASE).mock(return_value=httpx.Response(200, content=payload))
    adapter = nse_adapter(tmp_path)
    partition = date(2024, 1, 15)
    version = version_for("nse_bhavcopy_equity", partition)

    bars = adapter.normalize(adapter.parse(adapter.fetch(partition, version), version))

    assert bars
    assert all(bar.trade_date == partition for bar in bars)
    assert all(bar.venue == "NSE" for bar in bars)
