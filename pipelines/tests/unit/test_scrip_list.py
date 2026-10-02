"""Reading BSE's list of scrips and choosing the name it gives each ISIN."""

from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from pipelines.sources.bse.scrip_list import (
    SOURCE_ID,
    BseScripList,
    ScripListing,
    names_by_isin,
    parse_listings,
)
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import SchemaDrift

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "bse_scrip_list"
BASE = "https://api.bseindia.com/BseIndiaAPI/api"
READ_ON = date(2026, 10, 2)

RELIANCE = "INE002A01018"
EMAMI = "INE548C01032"
GLOSTER = "INE652C01016"
ELGI = "INE257B01024"


def recorded(status: str) -> bytes:
    return (CASSETTES / f"{status.lower()}.json").read_bytes()


def every_status() -> list[ScripListing]:
    return [
        listing
        for status in ("Active", "Suspended", "Delisted")
        for listing in parse_listings(recorded(status), status)
    ]


def test_each_security_is_read_with_its_scrip_code_isin_and_name() -> None:
    listings = parse_listings(recorded("Active"), "Active")

    reliance = next(listing for listing in listings if listing.isin == RELIANCE)
    assert reliance == ScripListing(
        scrip_code="500325", isin=RELIANCE, name="Reliance Industries Ltd", status="Active"
    )


def test_a_security_naming_no_isin_is_left_out() -> None:
    """A D S Diagnostics carries an empty ISIN, and Essar Investments `NA`."""
    active = parse_listings(recorded("Active"), "Active")
    suspended = parse_listings(recorded("Suspended"), "Suspended")

    assert len(active) == 5
    assert [listing.isin for listing in suspended] == ["INE294A01037"]


def test_spaces_inside_a_name_are_collapsed() -> None:
    delisted = parse_listings(recorded("Delisted"), "Delisted")

    assert {listing.name for listing in delisted if listing.isin == GLOSTER} == {"Gloster Ltd"}


def test_an_empty_list_names_nothing() -> None:
    assert parse_listings(b"[]", "Suspended") == ()


@pytest.mark.parametrize(
    "payload",
    [
        b"<html><body>Access Denied</body></html>",
        b'{"Table": []}',
        b'[{"SCRIP_CD": "500325", "Scrip_Name": "Reliance Industries Ltd", "Status": "Active"}]',
    ],
)
def test_an_answer_that_is_not_the_list_is_refused(payload: bytes) -> None:
    with pytest.raises(SchemaDrift):
        parse_listings(payload, "Active")


def test_an_answer_holding_another_status_is_refused() -> None:
    """The venue has answered a query with a list other than the one asked for."""
    with pytest.raises(SchemaDrift):
        parse_listings(recorded("Active"), "Delisted")


def test_the_latest_status_names_an_isin() -> None:
    """Reliance's buy-back window is delisted as RILBBPH; Emami's retired code as Emami Ltd."""
    names = names_by_isin(every_status(), {})

    assert names[RELIANCE] == "Reliance Industries Ltd"
    assert names[EMAMI] == "Emami Ltd-$"


def test_within_a_status_the_scrip_code_held_names_an_isin_then_the_lowest() -> None:
    """BSE lists Elgi Rubber's ISIN as delisted under two codes and two names."""
    listings = [
        ScripListing(
            scrip_code="590023", isin=ELGI, name="Elgi Rubber Company Ltd", status="Delisted"
        ),
        ScripListing(
            scrip_code="500131", isin=ELGI, name="Elgitread (India) Ltd", status="Delisted"
        ),
    ]

    assert names_by_isin(listings, {ELGI: {"590023"}})[ELGI] == "Elgi Rubber Company Ltd"
    assert names_by_isin(listings, {})[ELGI] == "Elgitread (India) Ltd"


def adapter(cache: DiskCache) -> BseScripList:
    client = ThrottledClient(
        SOURCE_ID,
        httpx.Client(headers={"User-Agent": "bitemporal (personal research)"}),
        Throttle(0.0),
        initial_backoff_seconds=0.001,
    )
    return BseScripList(client, cache, f"{BASE}/")


def test_a_status_is_asked_for_as_the_venues_list_page_asks() -> None:
    url = adapter(None).url_for("Delisted")  # type: ignore[arg-type]

    assert url == (
        f"{BASE}/ListofScripData_new/w?Group=&Scripcode=&segment=Equity&status=Delisted&scripName="
    )


@respx.mock
def test_a_list_is_read_once_a_day_with_a_browsers_headers(tmp_path: Path) -> None:
    route = respx.get(url__startswith=BASE).mock(
        return_value=httpx.Response(200, content=recorded("Suspended"))
    )
    reader = adapter(DiskCache(tmp_path))

    first = reader.fetch("Suspended", READ_ON)
    again = reader.fetch("Suspended", READ_ON)

    assert first == again == recorded("Suspended")
    assert route.call_count == 1
    sent = route.calls.last.request.headers
    assert "Chrome/" in sent["User-Agent"]
    assert sent["Referer"] == "https://www.bseindia.com/"


@respx.mock
def test_an_answer_that_is_not_the_list_is_never_cached(tmp_path: Path) -> None:
    respx.get(url__startswith=BASE).mock(return_value=httpx.Response(200, content=b"<html>"))

    with pytest.raises(SchemaDrift):
        adapter(DiskCache(tmp_path)).fetch("Active", READ_ON)

    assert not any(tmp_path.rglob("*.json"))
