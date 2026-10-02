"""BSE gross delivery, served as a zipped pipe delimited file to a plain client."""

from collections.abc import Mapping, Sequence
from datetime import date

from pipelines.models.market import DeliveryRecord
from pipelines.sources.archive import contents
from pipelines.sources.bse.bhavcopy import reject_error_page
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Answer, ThrottledClient
from pipelines.sources.delivery import DeliveryRow, held_to, normalize, parse_bse_delivery
from pipelines.sources.errors import UnknownSchemaVersion
from pipelines.sources.revalidation import recheck

SOURCE_ID = "bse_delivery"
VENUE = "BSE"
CACHE_SUFFIX = ".zip"
GROSS = "scbseall"


class BseDelivery:
    """Reads one trading day of BSE delivery figures.

    The archive is filed under the year and named by day and month alone, so a request for a date
    the venue holds nothing for answers with the home page rather than a status.
    """

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def url_for(self, partition: date) -> str:
        return f"{self._base_url}/{partition:%Y}/SCBSEALL{partition:%d%m}.zip"

    def fetch(self, partition: date, schema_version: str = GROSS) -> bytes:
        self._require(schema_version)
        key = partition.isoformat()
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        url = self.url_for(partition)
        answer = self._client.get_answer(url)
        reject_error_page(answer.content, url)
        held_to(self.parse(answer.content), partition, VENUE)
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, answer.content)
        self._cache.write_validators(SOURCE_ID, key, CACHE_SUFFIX, answer.validators)
        return answer.content

    def corrections(self, partition: date) -> list[tuple[date, bytes]]:
        """Each corrected file held for a day, with the day it was noticed."""
        return self._cache.versions(SOURCE_ID, partition.isoformat(), CACHE_SUFFIX)

    def recheck(self, partition: date, noticed_on: date) -> bytes | None:
        """Ask again for a day's file, holding a corrected one beside it."""
        url = self.url_for(partition)

        def ask(held: Mapping[str, str]) -> Answer | None:
            answer = self._client.get_if_changed(url, held)
            if answer is not None:
                reject_error_page(answer.content, url)
                held_to(self.parse(answer.content), partition, VENUE)
            return answer

        key = partition.isoformat()
        return recheck(self._cache, SOURCE_ID, key, CACHE_SUFFIX, noticed_on, ask, contents)

    def parse(self, payload: bytes, schema_version: str = GROSS) -> Sequence[DeliveryRow]:
        self._require(schema_version)
        return parse_bse_delivery(payload)

    def fallback_for(self, schema_version: str) -> str | None:
        return None

    def normalize(
        self, rows: Sequence[DeliveryRow], isin_for_scrip: dict[str, str]
    ) -> Sequence[DeliveryRecord]:
        return normalize(rows, VENUE, isin_for_scrip)

    def _require(self, schema_version: str) -> None:
        if schema_version != GROSS:
            raise UnknownSchemaVersion(f"{SOURCE_ID} has no parser for {schema_version}")
