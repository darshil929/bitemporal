"""BSE equity bhavcopy, served as a bare CSV to a plain client."""

from collections.abc import Sequence
from datetime import date

from pipelines.models.market import PriceBar
from pipelines.sources.bhavcopy import BhavcopyRow, normalize
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.errors import NotPublished, UnknownSchemaVersion
from pipelines.sources.legacy import parse_bse_legacy
from pipelines.sources.udiff import parse_udiff

SOURCE_ID = "bse_bhavcopy_equity"
VENUE = "BSE"
CACHE_SUFFIX = ".csv"

UDIFF = "udiff"
LEGACY = "bse_legacy"


class BseBhavcopy:
    """Reads one trading day of BSE equity prices."""

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def url_for(self, partition: date, schema_version: str) -> str:
        if schema_version == UDIFF:
            return f"{self._base_url}/BhavCopy_BSE_CM_0_0_0_{partition:%Y%m%d}_F_0000.CSV"
        if schema_version == LEGACY:
            return f"{self._base_url}/EQ_ISINCODE_{partition:%d%m%y}.CSV"
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no url for {schema_version}")

    def fetch(self, partition: date, schema_version: str = UDIFF) -> bytes:
        key = partition.isoformat()
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        url = self.url_for(partition, schema_version)
        payload = self._client.get(url)
        reject_error_page(payload, url)
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes, schema_version: str) -> Sequence[BhavcopyRow]:
        if schema_version == UDIFF:
            return parse_udiff(payload)
        if schema_version == LEGACY:
            return parse_bse_legacy(payload)
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no parser for {schema_version}")

    def normalize(self, records: Sequence[BhavcopyRow]) -> Sequence[PriceBar]:
        return normalize(records, VENUE)


def reject_error_page(payload: bytes, url: str) -> None:
    """BSE answers a request for a file it does not hold with its home page, carrying HTTP 200.

    Without this the page reaches the cache and every later run reads it back as a bhavcopy.
    """
    if payload.lstrip()[:1] == b"<":
        raise NotPublished(f"{SOURCE_ID} served a page rather than a file for {url}")
