"""NSE's lists of equity securities, the main board and the SME platform, served as CSV."""

import csv
import io
import logging
import re
from collections.abc import Iterable
from datetime import date

from pydantic import BaseModel

from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.errors import SchemaDrift, SourceUnavailable
from pipelines.sources.nse.bhavcopy import COOKIE_SOURCE_URL
from pipelines.sources.payload import decoded

logger = logging.getLogger(__name__)

SOURCE_ID = "nse_equity_list"
CACHE_SUFFIX = ".csv"

# Each board's list by the path the archive host serves it under, the main board first.
BOARDS = {
    "main": "content/equities/EQUITY_L.csv",
    "sme": "emerge/corporates/content/SME_EQUITY_L.csv",
}

REQUIRED_COLUMNS = frozenset({"SYMBOL", "NAME OF COMPANY", "ISIN NUMBER"})

ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


class EquityListing(BaseModel):
    """One security, under the symbol and name the list gives it."""

    symbol: str
    isin: str
    name: str


def parse_listings(payload: bytes) -> tuple[EquityListing, ...]:
    """Read one board's list, leaving out a row that names no ISIN."""
    rows = csv.reader(io.StringIO(decoded(payload, "list of equities")))
    # The SME list joins a column's words with underscores, and the main board pads them.
    header = [" ".join(name.replace("_", " ").split()).upper() for name in next(rows, [])]
    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        raise SchemaDrift(f"list of equities is missing {sorted(missing)}")

    listings = []
    unkeyed = 0
    for row in rows:
        record = dict(zip(header, (cell.strip() for cell in row), strict=False))
        if not any(record.values()):
            continue
        isin = record.get("ISIN NUMBER", "")
        name = " ".join(record.get("NAME OF COMPANY", "").split())
        if not ISIN.fullmatch(isin) or not name:
            unkeyed += 1
            continue
        listings.append(EquityListing(symbol=record["SYMBOL"], isin=isin, name=name))

    if unkeyed:
        logger.info(
            "securities naming no isin left out", extra={"source_id": SOURCE_ID, "count": unkeyed}
        )
    return tuple(listings)


def names_by_isin(listings: Iterable[EquityListing]) -> dict[str, str]:
    """The name the lists give each ISIN, the first board read standing where two name it."""
    names: dict[str, str] = {}
    for listing in listings:
        names.setdefault(listing.isin, listing.name)
    return names


class NseEquityList:
    """Reads one board's list of equities, held under the day it was read."""

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")
        self._holds_cookie = False

    def url_for(self, board: str) -> str:
        return f"{self._base_url}/{BOARDS[board]}"

    def fetch(self, board: str, collected_on: date) -> bytes:
        key = f"{board}-as-of-{collected_on:%Y%m%d}"
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        payload = self._read(self.url_for(board))
        # A response that is not the list, such as a page served in its place, is never held.
        parse_listings(payload)
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes, board: str) -> tuple[EquityListing, ...]:
        return parse_listings(payload)

    def _read(self, url: str) -> bytes:
        """Fetch through the session cookie the archive host requires, renewed once if refused."""
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
