"""NSE security-wise delivery, served as a bare CSV behind the same session cookie."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date

from pipelines.models.market import DeliveryRecord
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Answer, ThrottledClient
from pipelines.sources.delivery import (
    DeliveryRow,
    held_to,
    normalize,
    parse_nse_delivery,
    parse_nse_position,
)
from pipelines.sources.errors import SourceUnavailable, UnknownSchemaVersion
from pipelines.sources.nse.bhavcopy import COOKIE_SOURCE_URL
from pipelines.sources.revalidation import recheck

SOURCE_ID = "nse_delivery"
VENUE = "NSE"

FULL = "sec_bhavdata_full"
POSITION = "mto"
CACHE_SUFFIX = {FULL: ".csv", POSITION: ".dat"}


class NseDelivery:
    """Reads one trading day of NSE delivery figures, from either file NSE publishes them in.

    The full bhavdata file and the security-wise delivery position file carry the same figures.
    """

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")
        self._holds_cookie = False

    def url_for(self, partition: date, schema_version: str = FULL) -> str:
        if schema_version == FULL:
            return f"{self._base_url}/products/content/sec_bhavdata_full_{partition:%d%m%Y}.csv"
        if schema_version == POSITION:
            return f"{self._base_url}/archives/equities/mto/MTO_{partition:%d%m%Y}.DAT"
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no url for {schema_version}")

    def fetch(self, partition: date, schema_version: str = FULL) -> bytes:
        url = self.url_for(partition, schema_version)
        key = partition.isoformat()
        suffix = CACHE_SUFFIX[schema_version]
        cached = self._cache.read(SOURCE_ID, key, suffix)
        if cached is not None:
            return cached

        answer = self._through_cookie(lambda: self._client.get_answer(url))
        # A file describing another day is never held, or the day asked for could not be read again.
        held_to(self.parse(answer.content, schema_version), partition, VENUE)
        self._cache.write(SOURCE_ID, key, suffix, answer.content)
        self._cache.write_validators(SOURCE_ID, key, suffix, answer.validators)
        return answer.content

    def recheck(self, partition: date, noticed_on: date) -> bytes | None:
        """Ask again for a day's full file, holding a corrected one beside it."""
        url = self.url_for(partition, FULL)

        def ask(held: Mapping[str, str]) -> Answer | None:
            answer = self._through_cookie(lambda: self._client.get_if_changed(url, held))
            if answer is not None:
                held_to(self.parse(answer.content, FULL), partition, VENUE)
            return answer

        key = partition.isoformat()
        return recheck(self._cache, SOURCE_ID, key, CACHE_SUFFIX[FULL], noticed_on, ask)

    def parse(self, payload: bytes, schema_version: str = FULL) -> Sequence[DeliveryRow]:
        if schema_version == FULL:
            return parse_nse_delivery(payload)
        if schema_version == POSITION:
            return parse_nse_position(payload)
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no parser for {schema_version}")

    def fallback_for(self, schema_version: str) -> str | None:
        """The other file carrying the same figures, read for a trading day the first does not."""
        return POSITION if schema_version == FULL else None

    def normalize(
        self, rows: Sequence[DeliveryRow], isin_for_symbol: dict[str, str]
    ) -> Sequence[DeliveryRecord]:
        return normalize(rows, VENUE, isin_for_symbol)

    def _through_cookie[T](self, request: Callable[[], T]) -> T:
        self._obtain_cookie()
        try:
            return request()
        except SourceUnavailable:
            self._holds_cookie = False
            self._obtain_cookie()
            return request()

    def _obtain_cookie(self) -> None:
        if self._holds_cookie:
            return
        self._client.get(COOKIE_SOURCE_URL)
        self._holds_cookie = True
