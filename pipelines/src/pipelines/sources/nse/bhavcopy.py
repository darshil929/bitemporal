"""NSE equity bhavcopy, served as a zipped CSV behind a session cookie."""

import io
import zipfile
from collections.abc import Sequence
from datetime import date

from pipelines.models.market import PriceBar
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.errors import SourceUnavailable
from pipelines.sources.udiff import UdiffRow, normalize, parse_udiff

SOURCE_ID = "nse_bhavcopy_equity"
VENUE = "NSE"
CACHE_SUFFIX = ".csv.zip"

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

    def url_for(self, partition: date) -> str:
        return f"{self._base_url}/cm/BhavCopy_NSE_CM_0_0_0_{partition:%Y%m%d}_F_0000.csv.zip"

    def fetch(self, partition: date) -> bytes:
        key = partition.isoformat()
        archive = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)

        if archive is None:
            self._obtain_cookie()
            archive = self._client.get(self.url_for(partition))
            self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, archive)

        return _extract(archive)

    def parse(self, payload: bytes, schema_version: str) -> Sequence[UdiffRow]:
        return parse_udiff(payload)

    def normalize(self, records: Sequence[UdiffRow]) -> Sequence[PriceBar]:
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
