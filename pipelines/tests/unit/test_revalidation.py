"""Asking again for a day's file already held, and holding a corrected one beside it."""

import io
import zipfile
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from pipelines.sources.archive import extract_csv
from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Answer, Throttle, ThrottledClient
from pipelines.sources.errors import NotHeld, SourceUnavailable, WrongDay
from pipelines.sources.nse.bhavcopy import COOKIE_SOURCE_URL, NseBhavcopy
from pipelines.sources.nse.delivery import NseDelivery
from pipelines.sources.revalidation import recheck, unchanged

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
DAY = date(2026, 8, 14)
NOTICED_ON = date(2026, 8, 16)
HELD = {"etag": '"3bb12f5ede4cdd1:0"', "last-modified": "Fri, 14 Aug 2026 11:09:43 GMT"}


def client() -> ThrottledClient:
    return ThrottledClient("a_source", httpx.Client(), Throttle(0.0), initial_backoff_seconds=0.001)


def zipped(text: bytes, packed: tuple[int, ...] = (2026, 8, 14, 18, 0, 0)) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("day.csv", date_time=packed), text)  # type: ignore[arg-type]
    return buffer.getvalue()


def held(tmp_path: Path, payload: bytes, validators: Mapping[str, str] = HELD) -> DiskCache:
    cache = DiskCache(tmp_path)
    cache.write("a_source", "2026-08-14", ".csv", payload)
    cache.write_validators("a_source", "2026-08-14", ".csv", validators)
    return cache


def ask_again(
    cache: DiskCache, answer: Answer | None, content: Callable[[bytes], bytes] = unchanged
) -> tuple[bytes | None, list[dict[str, str]]]:
    asked: list[dict[str, str]] = []

    def ask(validators: Mapping[str, str]) -> Answer | None:
        asked.append(dict(validators))
        return answer

    changed = recheck(cache, "a_source", "2026-08-14", ".csv", NOTICED_ON, ask, content)
    return changed, asked


@respx.mock
def test_a_file_asked_for_again_sends_back_the_validators_held() -> None:
    route = respx.get("https://venue.test/day.csv").mock(return_value=httpx.Response(304))

    assert client().get_if_changed("https://venue.test/day.csv", HELD) is None
    assert route.calls.last.request.headers["If-None-Match"] == HELD["etag"]
    assert route.calls.last.request.headers["If-Modified-Since"] == HELD["last-modified"]


def test_a_file_held_without_validators_is_compared_in_full_once(tmp_path: Path) -> None:
    cache = held(tmp_path, b"a,b\n1,2\n", validators={})
    assert ask_again(cache, Answer(b"a,b\n1,2\n", {"etag": '"v1"'})) == (None, [{}])
    assert cache.read_validators("a_source", "2026-08-14", ".csv") == {"etag": '"v1"'}
    assert not list(tmp_path.rglob("*.as-of-*"))


def test_a_day_whose_file_is_not_held_cannot_be_asked_for_again(tmp_path: Path) -> None:
    """A day stored from a cache that no longer holds its file has nothing to compare against."""
    with pytest.raises(NotHeld):
        ask_again(DiskCache(tmp_path), Answer(b"a,b\n1,2\n", {"etag": '"v1"'}))
    assert not list(tmp_path.rglob("*"))


def test_a_corrected_file_is_held_beside_the_copy_it_corrects(tmp_path: Path) -> None:
    cache = held(tmp_path, b"a,b\n1,2\n")

    changed, _ = ask_again(cache, Answer(b"a,b\n1,3\n", {"etag": '"v2"'}))

    assert changed == b"a,b\n1,3\n"
    assert cache.read("a_source", "2026-08-14", ".csv") == b"a,b\n1,2\n"
    assert cache.latest("a_source", "2026-08-14", ".csv") == changed


def test_an_archive_packed_again_around_the_same_file_is_no_change(tmp_path: Path) -> None:
    cache = held(tmp_path, zipped(b"a,b\n1,2\n"))
    repacked = zipped(b"a,b\n1,2\n", packed=(2026, 8, 15, 7, 30, 0))

    assert ask_again(cache, Answer(repacked, {"etag": '"v2"'}), extract_csv)[0] is None


def test_an_answer_that_cannot_be_read_holds_nothing(tmp_path: Path) -> None:
    cache = held(tmp_path, zipped(b"a,b\n1,2\n"), validators={})
    with pytest.raises(SourceUnavailable):
        ask_again(cache, Answer(b"<html>", {"etag": '"page"'}), extract_csv)

    assert cache.read_validators("a_source", "2026-08-14", ".csv") == {}
    assert not list(tmp_path.rglob("*.as-of-*"))


@respx.mock
def test_bses_price_file_is_asked_for_again_with_its_validators(tmp_path: Path) -> None:
    payload = (CASSETTES / "bse_bhavcopy_equity" / "20260814.csv").read_bytes()
    first = httpx.Response(200, content=payload, headers={"ETag": '"v1"'})
    route = respx.get(url__startswith="https://www.bseindia.com").mock(
        side_effect=[first, httpx.Response(304)]
    )
    adapter = BseBhavcopy(client(), DiskCache(tmp_path), "https://www.bseindia.com/download/")
    adapter.fetch(DAY)

    assert adapter.recheck(DAY, NOTICED_ON) is None
    assert route.calls.last.request.headers["If-None-Match"] == '"v1"'


@respx.mock
def test_a_corrected_nse_price_file_is_held_beside_the_first(tmp_path: Path) -> None:
    archive = (CASSETTES / "nse_bhavcopy_equity" / "20260814.csv.zip").read_bytes()
    corrected = zipped(extract_csv(archive) + b"\n")
    respx.get(COOKIE_SOURCE_URL).mock(return_value=httpx.Response(200))
    respx.get(url__startswith="https://nsearchives.nseindia.com").mock(
        side_effect=[httpx.Response(200, content=archive), httpx.Response(200, content=corrected)]
    )
    adapter = NseBhavcopy(
        client(), DiskCache(tmp_path), "https://nsearchives.nseindia.com/content/"
    )

    adapter.fetch(DAY)

    assert adapter.recheck(DAY, NOTICED_ON) == corrected
    assert (tmp_path / "nse_bhavcopy_equity" / "2026-08-14.as-of-20260816.csv.zip").exists()


@respx.mock
def test_a_delivery_file_answered_for_another_day_is_not_held(tmp_path: Path) -> None:
    respx.get(COOKIE_SOURCE_URL).mock(return_value=httpx.Response(200))
    respx.get(url__startswith="https://nsearchives.nseindia.com").mock(
        side_effect=[
            httpx.Response(200, content=(CASSETTES / "nse_delivery" / "20260814.csv").read_bytes()),
            httpx.Response(200, content=(CASSETTES / "nse_delivery" / "20230615.csv").read_bytes()),
        ]
    )
    adapter = NseDelivery(client(), DiskCache(tmp_path), "https://nsearchives.nseindia.com")
    adapter.fetch(DAY)

    with pytest.raises(WrongDay):
        adapter.recheck(DAY, NOTICED_ON)

    assert not list(tmp_path.rglob("*.as-of-*"))
