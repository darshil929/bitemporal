"""BSE corporate actions, served as JSON for a range of ex-dates across every scrip code."""

import json
import logging
import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.errors import SchemaDrift
from pipelines.sources.payload import decoded
from pipelines.sources.ranges import calendar_years, range_key

logger = logging.getLogger(__name__)

SOURCE_ID = "bse_corporate_actions"
CACHE_SUFFIX = ".json"

REQUIRED_FIELDS = frozenset({"scrip_code", "Purpose", "exdate"})

# The endpoint answers a request carrying none of these with a page rather than JSON.
REQUIRED_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}

# The purpose is free text. Each pattern below names an action whose effect on the share count or
# on value is derivable from the text itself.
BONUS = re.compile(r"^bonus issue\s+(\d+)\s*:\s*(\d+)", re.IGNORECASE)
SPLIT = re.compile(
    r"^stock\s+split\s+from\s+rs\.?\s*([\d.]+)\s*/?-?\s*to\s+rs\.?\s*([\d.]+)", re.IGNORECASE
)
DIVIDEND = re.compile(r"dividend\s*-\s*rs\.?\s*-\s*([\d.]+)", re.IGNORECASE)
QUALIFIER = re.compile(r"^(interim|final|special)\s+dividend", re.IGNORECASE)
DEFAULT_QUALIFIER = "ordinary"

# The qualifier of an unhandled action is its purpose text, which a long one is cut to.
QUALIFIER_LIMIT = 64


def parse_purpose(
    purpose: str,
) -> tuple[str, str, Decimal | None, Decimal | None, Decimal | None]:
    """Read an action type and its terms out of the purpose text.

    Returns the type, a qualifier naming the kind of dividend, the share count before and after,
    and a dividend amount. An action whose terms are not in the text, a spin off or a scheme of
    arrangement, is reported as `unhandled`, qualified by the text in lower case so that two of
    them sharing an ex-date stay apart.
    """
    text = " ".join(purpose.split())

    bonus = BONUS.match(text)
    if bonus:
        received, held = Decimal(bonus.group(1)), Decimal(bonus.group(2))
        if received > 0 and held > 0:
            return "bonus", DEFAULT_QUALIFIER, held, held + received, None

    split = SPLIT.match(text)
    if split:
        old_face, new_face = Decimal(split.group(1)), Decimal(split.group(2))
        if old_face > 0 and new_face > 0:
            if new_face > old_face:
                return "consolidation", DEFAULT_QUALIFIER, new_face / old_face, Decimal(1), None
            return "split", DEFAULT_QUALIFIER, Decimal(1), old_face / new_face, None

    dividend = DIVIDEND.search(text)
    if dividend:
        kind = QUALIFIER.match(text)
        return (
            "dividend",
            kind.group(1).lower() if kind else DEFAULT_QUALIFIER,
            None,
            None,
            Decimal(dividend.group(1)),
        )

    return "unhandled", text.lower()[:QUALIFIER_LIMIT], None, None, None


def parse_actions(payload: bytes) -> tuple[dict[str, str], ...]:
    """Read the response into raw records, performing no interpretation."""
    try:
        document = json.loads(decoded(payload, "corporate actions"))
    except json.JSONDecodeError as error:
        raise SchemaDrift("corporate actions response is not json") from error
    if not isinstance(document, list):
        raise SchemaDrift("corporate actions response is not a list")

    for entry in document:
        missing = REQUIRED_FIELDS - set(entry)
        if missing:
            raise SchemaDrift(f"corporate action is missing {sorted(missing)}")

    return tuple(document)


def normalize(
    records: Sequence[dict[str, str]], isin_for_scrip: dict[str, str], as_of_date: date
) -> tuple[CorporateActionRecord, ...]:
    """Map raw records onto canonical actions.

    An action whose terms the text does not carry is recorded as `unhandled` with that text. A
    price move it caused is then marked rather than reading as a fall nothing explains.

    The endpoint repeats some rows verbatim, so an action already seen is recorded once.
    """
    actions: list[CorporateActionRecord] = []
    seen: set[tuple[str, str, str, str]] = set()
    unhandled: list[str] = []
    empty = 0

    outside: set[str] = set()

    for record in records:
        scrip_code = str(record["scrip_code"])
        isin = isin_for_scrip.get(scrip_code)
        if isin is None:
            outside.add(scrip_code)
            continue

        purpose = " ".join(record["Purpose"].split())
        action_type, qualifier, ratio_from, ratio_to, amount = parse_purpose(record["Purpose"])
        if action_type == "unhandled":
            if not purpose:
                # The row states nothing, so there is nothing to record or to mark a move with.
                empty += 1
                continue
            unhandled.append(f"{scrip_code} {record['exdate']} {purpose}")

        seal = (isin, action_type, record["exdate"], qualifier)
        if seal in seen:
            continue
        seen.add(seal)

        actions.append(
            CorporateActionRecord(
                isin=isin,
                action_type=action_type,
                ex_date=datetime.strptime(record["exdate"], "%Y%m%d").date(),  # noqa: DTZ007
                source_id=SOURCE_ID,
                as_of_date=as_of_date,
                qualifier=qualifier,
                ratio_from=ratio_from,
                ratio_to=ratio_to,
                dividend_amount=amount,
                purpose=purpose if action_type == "unhandled" else None,
            )
        )

    if outside:
        logger.info(
            "corporate actions for scrip codes outside the tracked universe",
            extra={"source_id": SOURCE_ID, "scrip_codes": len(outside), "kept": len(actions)},
        )

    if empty:
        logger.warning(
            "corporate actions carrying no purpose text left out",
            extra={"source_id": SOURCE_ID, "count": empty},
        )

    if unhandled:
        logger.warning(
            "corporate actions recorded without derivable terms",
            extra={"source_id": SOURCE_ID, "count": len(unhandled), "examples": unhandled[:5]},
        )

    return tuple(actions)


# The venue records no action before 2000.
FIRST_YEAR = 2000


def years(collected_on: date) -> list[tuple[date, date]]:
    """Every calendar year of ex-dates the venue has recorded or announced."""
    return calendar_years(FIRST_YEAR, collected_on)


class BseCorporateActions:
    """Reads every action the venue recorded with an ex-date inside a range, for every scrip code.

    A response already in the cache is read from disk and costs no request, whether this adapter
    fetched it or it was saved there from the venue's own corporate action page, which asks the
    endpoint the same question.
    """

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def url_for(self, first: date, last: date) -> str:
        return (
            f"{self._base_url}/DefaultData/w?ddlcategorys=E&ddlindustrys=&segment=0"
            f"&strSearch=D&Fdate={first:%Y%m%d}&TDate={last:%Y%m%d}&Purposecode=&scripcode="
        )

    def fetch(self, first: date, last: date, collected_on: date) -> bytes:
        key = range_key(first, last, collected_on)
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        payload = self._client.get(self.url_for(first, last), REQUIRED_HEADERS)
        # A response that is not the answer, such as the page served in its place, is never held.
        parse_actions(payload)
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes) -> tuple[dict[str, str], ...]:
        return parse_actions(payload)

    def normalize(
        self, records: Sequence[dict[str, str]], isin_for_scrip: dict[str, str], as_of_date: date
    ) -> tuple[CorporateActionRecord, ...]:
        return normalize(records, isin_for_scrip, as_of_date)
