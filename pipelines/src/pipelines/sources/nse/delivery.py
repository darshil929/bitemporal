"""NSE security-wise delivery, served as a bare CSV behind the same session cookie."""

from collections.abc import Sequence
from datetime import date

from pipelines.models.market import DeliveryRecord
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.delivery import DeliveryRow, normalize, parse_nse_delivery
from pipelines.sources.errors import SourceUnavailable
from pipelines.sources.nse.bhavcopy import COOKIE_SOURCE_URL

SOURCE_ID = "nse_delivery"
VENUE = "NSE"
CACHE_SUFFIX = ".csv"


class NseDelivery:
    """Reads one trading day of NSE delivery figures."""

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")
        self._holds_cookie = False

    def url_for(self, partition: date) -> str:
        return f"{self._base_url}/products/content/sec_bhavdata_full_{partition:%d%m%Y}.csv"

    def fetch(self, partition: date) -> bytes:
        key = partition.isoformat()
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        payload = self._read(self.url_for(partition))
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes) -> Sequence[DeliveryRow]:
        return parse_nse_delivery(payload)

    def normalize(
        self, rows: Sequence[DeliveryRow], isin_for_symbol: dict[str, str]
    ) -> Sequence[DeliveryRecord]:
        return normalize(rows, VENUE, isin_for_symbol)

    def _read(self, url: str) -> bytes:
        self._obtain_cookie()
        try:
            return self._client.get(url)
        except SourceUnavailable:
            self._holds_cookie = False
            self._obtain_cookie()
            return self._client.get(url)

    def _obtain_cookie(self) -> None:
        if self._holds_cookie:
            return
        self._client.get(COOKIE_SOURCE_URL)
        self._holds_cookie = True
