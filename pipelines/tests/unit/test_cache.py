"""The disk cache serves a stored response without a second request."""

from pathlib import Path

from pipelines.sources.cache import DiskCache

SOURCE_ID = "bse_bhavcopy_equity"
PARTITION = "2026-07-31"
SUFFIX = ".csv"


def test_a_missing_entry_reads_as_none(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)

    assert cache.read(SOURCE_ID, PARTITION, SUFFIX) is None


def test_a_written_entry_reads_back_unchanged(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    payload = b"TradDt,ISIN\n2026-07-31,INE002A01018\n"

    cache.write(SOURCE_ID, PARTITION, SUFFIX, payload)

    assert cache.read(SOURCE_ID, PARTITION, SUFFIX) == payload


def test_entries_are_separated_by_source(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    cache.write(SOURCE_ID, PARTITION, SUFFIX, b"bse")

    assert cache.read("nse_bhavcopy_equity", PARTITION, SUFFIX) is None
