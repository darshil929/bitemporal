"""NSE equity bhavcopy, served as a zipped CSV behind a session cookie."""

import io
import zipfile
from collections.abc import Sequence
from datetime import date

from pipelines.models.market import PriceBar
from pipelines.sources.bhavcopy import BhavcopyRow, normalize
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.errors import SourceUnavailable, UnknownSchemaVersion
from pipelines.sources.legacy import parse_nse_legacy
from pipelines.sources.udiff import parse_udiff

SOURCE_ID = "nse_bhavcopy_equity"
VENUE = "NSE"
CACHE_SUFFIX = ".csv.zip"

UDIFF = "udiff"
LEGACY = "nse_legacy"

# The archive host drops a request carrying no cookie, without answering. A cookie is issued by
# the main site, so one page there precedes the first archive read.
COOKIE_SOURCE_URL = "https://www.nseindia.com/option-chain"


class NseBhavcopy:
    """Reads one trading day of NSE equity prices."""

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")
        self._holds_cookie = False

    def url_for(self, partition: date, schema_version: str) -> str:
        if schema_version == UDIFF:
            return f"{self._base_url}/cm/BhavCopy_NSE_CM_0_0_0_{partition:%Y%m%d}_F_0000.csv.zip"
        if schema_version == LEGACY:
            month = f"{partition:%b}".upper()
            return (
                f"{self._base_url}/historical/EQUITIES/{partition:%Y}/{month}"
                f"/cm{partition:%d}{month}{partition:%Y}bhav.csv.zip"
            )
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no url for {schema_version}")

    def fetch(self, partition: date, schema_version: str = UDIFF) -> bytes:
        key = partition.isoformat()
        archive = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)

        if archive is None:
            archive = self._read_archive(self.url_for(partition, schema_version))
            self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, archive)

        return _extract(archive)

    def _read_archive(self, url: str) -> bytes:
        """Fetch through the session cookie, collecting a fresh one if the held one has expired.

        A cookie outlives a single request but not a backfill, and the archive host answers an
        expired one the same way it answers none at all.
        """
        self._obtain_cookie()
        try:
            return self._client.get(url)
        except SourceUnavailable:
            self._holds_cookie = False
            self._obtain_cookie()
            return self._client.get(url)

    def parse(self, payload: bytes, schema_version: str) -> Sequence[BhavcopyRow]:
        if schema_version == UDIFF:
            return parse_udiff(payload)
        if schema_version == LEGACY:
            return parse_nse_legacy(payload)
        raise UnknownSchemaVersion(f"{SOURCE_ID} has no parser for {schema_version}")

    def normalize(self, records: Sequence[BhavcopyRow]) -> Sequence[PriceBar]:
        return normalize(records, VENUE)

    def _obtain_cookie(self) -> None:
        if self._holds_cookie:
            return
        self._client.get(COOKIE_SOURCE_URL)
        self._holds_cookie = True


def _extract(archive: bytes) -> bytes:
    """Return the single CSV the archive carries."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            names = [name for name in opened.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise SourceUnavailable(f"archive holds {len(names)} csv entries, expected one")
            return opened.read(names[0])
    except zipfile.BadZipFile as error:
        raise SourceUnavailable("archive is not a zip file") from error
