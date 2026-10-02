"""BSE equity bhavcopy, served to a plain client: bare CSV after the cutover, zipped before."""

from collections.abc import Mapping, Sequence
from datetime import date

from pipelines.models.market import PriceBar
from pipelines.sources.archive import extract_csv
from pipelines.sources.bhavcopy import BhavcopyRow, normalize
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Answer, ThrottledClient
from pipelines.sources.errors import NotPublished, UnknownSchemaVersion
from pipelines.sources.legacy import parse_bse_legacy, parse_bse_scrip
from pipelines.sources.revalidation import recheck
from pipelines.sources.udiff import parse_udiff

SOURCE_ID = "bse_bhavcopy_equity"
VENUE = "BSE"
CACHE_SUFFIX = ".csv"
# The scrip code file for a day is held beside the ISIN file BSE served for the same day.
SCRIP_CACHE_SUFFIX = ".scrip.csv"

UDIFF = "udiff"
LEGACY = "bse_legacy"
SCRIP = "bse_scrip"
ZIPPED = frozenset({LEGACY, SCRIP})


class BseBhavcopy:
    """Reads one trading day of BSE equity prices."""

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def url_for(self, partition: date, schema_version: str) -> str:
        """The legacy file is only served zipped; the plain CSV covers recent days alone."""
        if schema_version == UDIFF:
            return f"{self._base_url}/BhavCopy_BSE_CM_0_0_0_{partition:%Y%m%d}_F_0000.CSV"
        if schema_version == LEGACY:
            return f"{self._base_url}/EQ_ISINCODE_{partition:%d%m%y}.zip"
        if schema_version == SCRIP:
            return f"{self._base_url}/EQ{partition:%d%m%y}_CSV.ZIP"
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no url for {schema_version}")

    def fetch(self, partition: date, schema_version: str = UDIFF) -> bytes:
        key = partition.isoformat()
        suffix = SCRIP_CACHE_SUFFIX if schema_version == SCRIP else CACHE_SUFFIX
        cached = self._cache.read(SOURCE_ID, key, suffix)
        if cached is not None:
            return cached

        url = self.url_for(partition, schema_version)
        answer = self._client.get_answer(url)
        payload = answer.content
        reject_error_page(payload, url)
        if schema_version in ZIPPED:
            payload = extract_csv(payload)
        self._cache.write(SOURCE_ID, key, suffix, payload)
        if schema_version == UDIFF:
            self._cache.write_validators(SOURCE_ID, key, suffix, answer.validators)
        return payload

    def corrections(self, partition: date) -> list[tuple[date, bytes]]:
        """Each corrected file held for a day in the current format, with the day it was noticed."""
        return self._cache.versions(SOURCE_ID, partition.isoformat(), CACHE_SUFFIX)

    def recheck(self, partition: date, noticed_on: date) -> bytes | None:
        """Ask again for a day's file in the current format, holding a corrected one beside it."""
        url = self.url_for(partition, UDIFF)

        def ask(held: Mapping[str, str]) -> Answer | None:
            answer = self._client.get_if_changed(url, held)
            if answer is not None:
                reject_error_page(answer.content, url)
            return answer

        return recheck(self._cache, SOURCE_ID, partition.isoformat(), CACHE_SUFFIX, noticed_on, ask)

    def parse(
        self, payload: bytes, schema_version: str, partition: date | None = None
    ) -> Sequence[BhavcopyRow]:
        if schema_version == UDIFF:
            return parse_udiff(payload)
        if schema_version == LEGACY:
            return parse_bse_legacy(payload, partition)
        if schema_version == SCRIP:
            return parse_bse_scrip(payload, partition)
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no parser for {schema_version}")

    def normalize(self, records: Sequence[BhavcopyRow]) -> Sequence[PriceBar]:
        return normalize(records, VENUE)


def reject_error_page(payload: bytes, url: str) -> None:
    """BSE answers a request for a file it does not hold with its home page, carrying HTTP 200.

    Without this the page reaches the cache and every later run reads it back as a bhavcopy.
    """
    if payload.lstrip()[:1] == b"<":
        raise NotPublished(f"{SOURCE_ID} served a page rather than a file for {url}")
