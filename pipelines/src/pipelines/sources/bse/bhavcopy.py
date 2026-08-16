"""BSE equity bhavcopy, served as a bare CSV to a plain client."""

from collections.abc import Sequence
from datetime import date

from pipelines.models.market import PriceBar
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.udiff import UdiffRow, normalize, parse_udiff

SOURCE_ID = "bse_bhavcopy_equity"
VENUE = "BSE"
CACHE_SUFFIX = ".csv"


class BseBhavcopy:
    """Reads one trading day of BSE equity prices."""

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def url_for(self, partition: date) -> str:
        return f"{self._base_url}/BhavCopy_BSE_CM_0_0_0_{partition:%Y%m%d}_F_0000.CSV"

    def fetch(self, partition: date) -> bytes:
        key = partition.isoformat()
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        payload = self._client.get(self.url_for(partition))
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes, schema_version: str) -> Sequence[UdiffRow]:
        return parse_udiff(payload)

    def normalize(self, records: Sequence[UdiffRow]) -> Sequence[PriceBar]:
        return normalize(records, VENUE)
