"""BSE's list of scrips: every equity security the venue lists under one status, served as JSON."""

import json
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import date

from pydantic import BaseModel

from pipelines.sources.bse.api import REQUIRED_HEADERS
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.errors import SchemaDrift
from pipelines.sources.payload import decoded

logger = logging.getLogger(__name__)

SOURCE_ID = "bse_scrip_list"
CACHE_SUFFIX = ".json"

# The venue's list page asks for one status at a time, the latest first.
STATUSES = ("Active", "Suspended", "Delisted")

REQUIRED_FIELDS = frozenset({"SCRIP_CD", "Scrip_Name", "ISIN_NUMBER", "Status"})

ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


class ScripListing(BaseModel):
    """One security, under the scrip code, name and status the list gives it."""

    scrip_code: str
    isin: str
    name: str
    status: str


def parse_listings(payload: bytes, status: str) -> tuple[ScripListing, ...]:
    """Read the answer for one status, leaving out a security that names no ISIN.

    A security listed before ISINs were issued, and many delisted since, carries `NA` or nothing.
    An answer holding another status than the one asked for is not the answer.
    """
    try:
        document = json.loads(decoded(payload, "list of scrips"))
    except json.JSONDecodeError as error:
        raise SchemaDrift("list of scrips response is not json") from error
    if not isinstance(document, list):
        raise SchemaDrift("list of scrips response is not a list")

    listings = []
    unkeyed = 0
    for entry in document:
        if not isinstance(entry, dict):
            raise SchemaDrift("list of scrips record is not an object")
        missing = REQUIRED_FIELDS - set(entry)
        if missing:
            raise SchemaDrift(f"list of scrips record is missing {sorted(missing)}")
        if str(entry["Status"]).strip().lower() != status.lower():
            raise SchemaDrift(f"list of {status} scrips holds a {entry['Status']} scrip")
        isin = str(entry["ISIN_NUMBER"] or "").strip()
        name = " ".join(str(entry["Scrip_Name"] or "").split())
        if not ISIN.fullmatch(isin) or not name:
            unkeyed += 1
            continue
        listings.append(
            ScripListing(
                scrip_code=str(entry["SCRIP_CD"]).strip(), isin=isin, name=name, status=status
            )
        )

    if unkeyed:
        logger.info(
            "scrips naming no isin left out",
            extra={"source_id": SOURCE_ID, "status": status, "count": unkeyed},
        )
    return tuple(listings)


def names_by_isin(
    listings: Iterable[ScripListing], held_codes: Mapping[str, set[str]]
) -> dict[str, str]:
    """The name the list gives each ISIN.

    BSE lists an ISIN more than once where a buy-back window or a retired scrip code carried it,
    under a code of its own and often an abbreviated name. The latest status stands, then the scrip
    code `held_codes` holds the ISIN under, then the lowest.
    """
    rank = {status: index for index, status in enumerate(STATUSES)}

    def precedence(listing: ScripListing) -> tuple[int, bool, int, str]:
        return (
            rank.get(listing.status, len(STATUSES)),
            listing.scrip_code not in held_codes.get(listing.isin, set()),
            len(listing.scrip_code),
            listing.scrip_code,
        )

    chosen: dict[str, ScripListing] = {}
    for listing in listings:
        standing = chosen.get(listing.isin)
        if standing is None or precedence(listing) < precedence(standing):
            chosen[listing.isin] = listing
    return {isin: listing.name for isin, listing in chosen.items()}


class BseScripList:
    """Reads the venue's list of scrips one status at a time, as its own list page asks.

    The list changes as securities list and leave, so an answer is held under the day it was read.
    """

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def url_for(self, status: str) -> str:
        # The query the list page sends; BseIndiaApi asks the older ListofScripData instead.
        return (
            f"{self._base_url}/ListofScripData_new/w?Group=&Scripcode=&segment=Equity"
            f"&status={status}&scripName="
        )

    def fetch(self, status: str, collected_on: date) -> bytes:
        key = f"{status.lower()}-as-of-{collected_on:%Y%m%d}"
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        payload = self._client.get(self.url_for(status), REQUIRED_HEADERS)
        # A response that is not the list asked for, such as a page served in its place, is never
        # held.
        parse_listings(payload, status)
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes, status: str) -> tuple[ScripListing, ...]:
        return parse_listings(payload, status)
