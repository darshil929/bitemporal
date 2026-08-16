"""The client spaces requests, retries transient failures and reports an absent file."""

import time

import httpx
import pytest
import respx

from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import NotPublished, SourceUnavailable

SOURCE_ID = "bse_bhavcopy_equity"
URL = "https://example.test/BhavCopy_20260731.CSV"
PAYLOAD = b"TradDt,ISIN\n"


def build_client() -> ThrottledClient:
    return ThrottledClient(SOURCE_ID, httpx.Client(), Throttle(0.0), initial_backoff_seconds=0.001)


@respx.mock
def test_a_successful_response_returns_its_body() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=PAYLOAD))

    assert build_client().get(URL) == PAYLOAD


@respx.mock
def test_a_rate_limited_response_is_retried_until_it_succeeds() -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, content=PAYLOAD),
        ]
    )

    assert build_client().get(URL) == PAYLOAD
    assert route.call_count == 3


@respx.mock
def test_a_missing_file_is_reported_as_unpublished() -> None:
    """A holiday and a file the venue has not released yet both answer 404."""
    route = respx.get(URL).mock(return_value=httpx.Response(404))

    with pytest.raises(NotPublished):
        build_client().get(URL)

    assert route.call_count == 1


def test_a_client_error_is_not_retried() -> None:
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(403))

        with pytest.raises(SourceUnavailable):
            build_client().get(URL)

        assert route.call_count == 1


@respx.mock
def test_a_transport_failure_is_retried_then_reported() -> None:
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(SourceUnavailable):
        build_client().get(URL)

    assert route.call_count == 5


def test_the_throttle_spaces_successive_releases() -> None:
    interval = 0.05
    throttle = Throttle(interval)

    throttle.wait()
    started = time.monotonic()
    throttle.wait()

    assert time.monotonic() - started >= interval
