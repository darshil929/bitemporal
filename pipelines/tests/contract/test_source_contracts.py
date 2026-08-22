"""Assertions that each source still answers with the columns its parser reads.

These hit the real endpoints, so they run in the nightly workflow and never in pull request CI.
A format change is caught here rather than by a parser failing halfway through a backfill.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.bse.corporate_actions import BseCorporateActions
from pipelines.sources.bse.delivery import BseDelivery
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import NotPublished, SourceError
from pipelines.sources.nse.bhavcopy import NseBhavcopy
from pipelines.sources.nse.delivery import NseDelivery
from pipelines.sources.registry import load_definitions

pytestmark = pytest.mark.contract

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
IDENTIFYING_USER_AGENT = "bitemporal (personal research)"

# A venue publishes some hours after the close, so the newest day is not a fair target.
FIRST_CANDIDATE = 3
CANDIDATES = 12

RELIANCE_SCRIP = "500325"


def definitions() -> dict[str, object]:
    return {item.source_id: item for item in load_definitions()}


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> DiskCache:
    """A cache of its own, so a contract check reads the venue rather than yesterday's copy."""
    return DiskCache(Path(tmp_path_factory.mktemp("contract")))


@pytest.fixture(scope="module")
def plain() -> Iterator[httpx.Client]:
    with httpx.Client(
        headers={"User-Agent": IDENTIFYING_USER_AGENT}, follow_redirects=True
    ) as client:
        yield client


@pytest.fixture(scope="module")
def browser() -> Iterator[httpx.Client]:
    with httpx.Client(
        headers={"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
    ) as client:
        yield client


def recent_days() -> list[date]:
    today = date.today()  # noqa: DTZ011
    days = []
    offset = FIRST_CANDIDATE
    while len(days) < CANDIDATES:
        candidate = today - timedelta(days=offset)
        if candidate.weekday() < 5:
            days.append(candidate)
        offset += 1
    return days


def first_published(adapter: object, versioned: bool) -> tuple[bytes, date, str]:
    """Walk back until a day the venue published, so a holiday does not fail the check."""
    definition = definitions()[adapter.source_id]  # type: ignore[attr-defined]
    for day in recent_days():
        version = definition.version_for(day)  # type: ignore[attr-defined]
        try:
            payload = (
                adapter.fetch(day, version)  # type: ignore[attr-defined]
                if versioned
                else adapter.fetch(day)  # type: ignore[attr-defined]
            )
        except NotPublished:
            continue
        except SourceError as error:
            pytest.fail(f"{adapter.source_id} unreachable: {error}")  # type: ignore[attr-defined]
        return payload, day, version
    pytest.fail(f"{adapter.source_id} published nothing in the last {CANDIDATES} weekdays")  # type: ignore[attr-defined]


def client(source_id: str, transport: httpx.Client) -> ThrottledClient:
    return ThrottledClient(source_id, transport, Throttle(2.0))


def test_the_bse_bhavcopy_still_carries_the_columns_it_is_read_for(
    cache: DiskCache, plain: httpx.Client
) -> None:
    adapter = BseBhavcopy(
        client("bse_bhavcopy_equity", plain),
        cache,
        definitions()["bse_bhavcopy_equity"].base_url,  # type: ignore[attr-defined]
    )
    payload, day, version = first_published(adapter, versioned=True)

    rows = adapter.parse(payload, version)

    assert rows, f"bse published {day} with no rows"
    assert adapter.normalize(rows), "no row survived the equity series filter"


def test_the_nse_bhavcopy_still_carries_the_columns_it_is_read_for(
    cache: DiskCache, browser: httpx.Client
) -> None:
    adapter = NseBhavcopy(
        client("nse_bhavcopy_equity", browser),
        cache,
        definitions()["nse_bhavcopy_equity"].base_url,  # type: ignore[attr-defined]
    )
    payload, day, version = first_published(adapter, versioned=True)

    rows = adapter.parse(payload, version)

    assert rows, f"nse published {day} with no rows"
    assert adapter.normalize(rows), "no row survived the equity series filter"


def test_the_bse_delivery_file_still_carries_its_columns(
    cache: DiskCache, plain: httpx.Client
) -> None:
    adapter = BseDelivery(
        client("bse_delivery", plain),
        cache,
        definitions()["bse_delivery"].base_url,  # type: ignore[attr-defined]
    )
    payload, day, _ = first_published(adapter, versioned=False)

    assert adapter.parse(payload), f"bse published delivery for {day} with no rows"


def test_the_nse_delivery_file_still_carries_its_columns(
    cache: DiskCache, browser: httpx.Client
) -> None:
    adapter = NseDelivery(
        client("nse_delivery", browser),
        cache,
        definitions()["nse_delivery"].base_url,  # type: ignore[attr-defined]
    )
    payload, day, _ = first_published(adapter, versioned=False)

    assert adapter.parse(payload), f"nse published delivery for {day} with no rows"


def test_the_corporate_action_endpoint_still_answers_with_its_fields(
    cache: DiskCache, plain: httpx.Client
) -> None:
    """The purpose text is free form, so a known scrip is read for terms the parser recognises."""
    adapter = BseCorporateActions(
        client("bse_corporate_actions", plain), cache, "https://api.bseindia.com/BseIndiaAPI/api"
    )

    records = adapter.parse(adapter.fetch(RELIANCE_SCRIP))
    actions = adapter.normalize(records, {RELIANCE_SCRIP: "INE002A01018"}, date.today())  # noqa: DTZ011

    assert records, "the endpoint answered with no records"
    assert any(item.action_type == "bonus" for item in actions), "no bonus was recognised"
