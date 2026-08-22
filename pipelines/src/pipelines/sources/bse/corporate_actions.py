"""BSE corporate actions, served as JSON keyed on scrip code."""

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


def parse_purpose(
    purpose: str,
) -> tuple[str, str, Decimal | None, Decimal | None, Decimal | None]:
    """Read an action type and its terms out of the purpose text.

    Returns the type, a qualifier naming the kind of dividend, the share count before and after,
    and a dividend amount. An action whose terms are not in the text, a spin off or a scheme of
    arrangement, is reported as `unhandled` so that the caller records it rather than mistaking it
    for nothing having happened.
    """
    text = " ".join(purpose.split())

    bonus = BONUS.match(text)
    if bonus:
        received, held = Decimal(bonus.group(1)), Decimal(bonus.group(2))
        return "bonus", DEFAULT_QUALIFIER, held, held + received, None

    split = SPLIT.match(text)
    if split:
        old_face, new_face = Decimal(split.group(1)), Decimal(split.group(2))
        if new_face <= 0:
            raise SchemaDrift(f"split names a face value of {new_face}: {text}")
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

    return "unhandled", DEFAULT_QUALIFIER, None, None, None


def parse_actions(payload: bytes) -> tuple[dict[str, str], ...]:
    """Read the response into raw records, performing no interpretation."""
    try:
        document = json.loads(payload.decode("utf-8"))
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
    """Map raw records onto canonical actions, dropping those with no derivable terms.

    The endpoint repeats some rows verbatim, so an action already seen is recorded once.
    """
    actions: list[CorporateActionRecord] = []
    seen: set[tuple[str, str, str, str]] = set()
    unhandled: list[str] = []

    for record in records:
        scrip_code = str(record["scrip_code"])
        isin = isin_for_scrip.get(scrip_code)
        if isin is None:
            continue

        action_type, qualifier, ratio_from, ratio_to, amount = parse_purpose(record["Purpose"])
        if action_type == "unhandled":
            unhandled.append(f"{scrip_code} {record['exdate']} {record['Purpose'].strip()}")
            continue

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
            )
        )

    if unhandled:
        logger.warning(
            "corporate actions carry no derivable terms",
            extra={"source_id": SOURCE_ID, "count": len(unhandled), "examples": unhandled[:5]},
        )

    return tuple(actions)


class BseCorporateActions:
    """Reads the full action history for one scrip code.

    The endpoint answers per scrip rather than per date, so a partition here is a scrip code and
    the response covers every action the venue has recorded for it.
    """

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def url_for(self, scrip_code: str) -> str:
        return (
            f"{self._base_url}/DefaultData/w?ddlcategorys=E&ddlindustrys=&segment=0"
            f"&strSearch=S&Fdate=&TDate=&Purposecode=&scripcode={scrip_code}"
        )

    def fetch(self, scrip_code: str) -> bytes:
        cached = self._cache.read(SOURCE_ID, scrip_code, CACHE_SUFFIX)
        if cached is not None:
            return cached

        payload = self._client.get(self.url_for(scrip_code), REQUIRED_HEADERS)
        self._cache.write(SOURCE_ID, scrip_code, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes) -> tuple[dict[str, str], ...]:
        return parse_actions(payload)

    def normalize(
        self, records: Sequence[dict[str, str]], isin_for_scrip: dict[str, str], as_of_date: date
    ) -> tuple[CorporateActionRecord, ...]:
        return normalize(records, isin_for_scrip, as_of_date)
