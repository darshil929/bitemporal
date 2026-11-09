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


def test_a_response_set_aside_reads_as_not_held_and_is_kept_numbered(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    cache.write(SOURCE_ID, PARTITION, SUFFIX, b"first")
    first = cache.set_aside(SOURCE_ID, PARTITION, SUFFIX)
    cache.write(SOURCE_ID, PARTITION, SUFFIX, b"second")
    second = cache.set_aside(SOURCE_ID, PARTITION, SUFFIX)

    assert cache.read(SOURCE_ID, PARTITION, SUFFIX) is None
    assert first is not None and first.name == f"{PARTITION}.refused-1{SUFFIX}"
    assert second is not None and second.read_bytes() == b"second"
    assert first.read_bytes() == b"first"
    assert cache.set_aside(SOURCE_ID, PARTITION, SUFFIX) is None
