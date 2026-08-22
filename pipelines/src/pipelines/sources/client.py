"""Throttled, retrying HTTP access to venue endpoints."""

import logging
import threading
import time
from collections.abc import Mapping

import httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from pipelines.sources.errors import NotPublished, SourceUnavailable

logger = logging.getLogger(__name__)

# 429 and the 5xx family are transient. A 4xx other than 429 describes the request, and repeating
# it produces the same answer.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0


class Throttle:
    """Spaces successive requests by at least the configured interval."""

    def __init__(self, minimum_interval_seconds: float) -> None:
        self._interval = minimum_interval_seconds
        self._lock = threading.Lock()
        self._released_at = float("-inf")

    def wait(self) -> None:
        with self._lock:
            remaining = self._interval - (time.monotonic() - self._released_at)
            if remaining > 0:
                time.sleep(remaining)
            self._released_at = time.monotonic()


def _is_transient(exception: BaseException) -> bool:
    if isinstance(exception, httpx.TransportError):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in RETRYABLE_STATUS
    return False


class ThrottledClient:
    """Reads one source, spacing requests and retrying transient failures.

    A 404 raises `NotPublished` rather than an error: a venue publishes nothing on a holiday and
    releases a trading day's file some hours after the close.
    """

    def __init__(
        self,
        source_id: str,
        client: httpx.Client,
        throttle: Throttle,
        initial_backoff_seconds: float = INITIAL_BACKOFF_SECONDS,
    ) -> None:
        self.source_id = source_id
        self._client = client
        self._throttle = throttle
        self._retrying = Retrying(
            retry=retry_if_exception(_is_transient),
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=wait_exponential_jitter(initial=initial_backoff_seconds, max=MAX_BACKOFF_SECONDS),
            reraise=True,
        )

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        try:
            return self._retrying(self._request, url, headers)
        except (httpx.HTTPStatusError, httpx.TransportError) as error:
            raise SourceUnavailable(f"{self.source_id} did not serve {url}") from error

    def _request(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        self._throttle.wait()
        response = self._client.get(url, headers=dict(headers) if headers else None)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotPublished(f"{self.source_id} has nothing at {url}")

        if response.status_code in RETRYABLE_STATUS:
            logger.warning(
                "source responded with a retryable status",
                extra={
                    "source_id": self.source_id,
                    "url": url,
                    "status_code": response.status_code,
                },
            )

        response.raise_for_status()
        return response.content
