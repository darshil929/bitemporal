"""NSE corporate actions, served as JSON for a range of ex-dates across every listed security.

Read to check BSE's actions rather than to adjust prices. Each row names an ISIN, but for an
instrument that has changed face value it can be one the instrument carried years earlier, so a
row is recorded under the ISIN that ISIN has since become.
"""

import json
import logging
import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.sources.bhavcopy import EQUITY_SERIES
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import ThrottledClient
from pipelines.sources.errors import SchemaDrift, SourceUnavailable
from pipelines.sources.payload import decoded
from pipelines.sources.ranges import calendar_years, range_key

logger = logging.getLogger(__name__)

SOURCE_ID = "nse_corporate_actions"
CACHE_SUFFIX = ".json"
EX_DATE_FORMAT = "%d-%b-%Y"

# The venue records no action before 1995.
FIRST_YEAR = 1995

REQUIRED_FIELDS = frozenset({"symbol", "series", "isin", "exDate", "subject"})

# The endpoint answers only a session that has loaded the filings page, and only with it as referrer.
FILINGS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
REQUIRED_HEADERS = {"Accept": "application/json, text/plain, */*", "Referer": FILINGS_PAGE}

DEFAULT_QUALIFIER = "ordinary"
EMPTY_SUBJECTS = frozenset({"", "nil", "na"})
QUALIFIER_LIMIT = 64

# The subject is free text, worded one way since about 2019 and several ways before. A bonus and a
# split can share one subject, and a dividend is sometimes stated as a percentage of face value,
# which is left as text. A bonus of debentures issues no shares.
BONUS = re.compile(r"\bbonus\b(?![^0-9]*debenture)\s*-?\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)
FACE_VALUE_CHANGE = re.compile(
    r"(split|sub-division|consolidation)[^0-9]*?from\s*r[es]\.?\s*([\d.]+)[^0-9]*?to\s*r[es]\.?\s*([\d.]+)",
    re.IGNORECASE,
)
DIVIDEND = re.compile(
    r"(interim|final|special)?\s*dividend\s*(?:of\s*)?[-:]?\s*r[es]\.?\s*([\d.]+)", re.IGNORECASE
)
# A dividend the subject names but states in no parsable amount, such as a percentage of face value.
UNSTATED_DIVIDEND = re.compile(r"\bdiv(?!is)", re.IGNORECASE)
# A subject naming only a meeting or a book closure, or nothing at all, announces no action.
NOTICE = re.compile(
    r"\b(agm|egm|general meeting|book closure|election|postal ballot)\b", re.IGNORECASE
)

type Terms = tuple[str, str, Decimal | None, Decimal | None, Decimal | None]


def _number(text: str) -> Decimal | None:
    try:
        value = Decimal(text.rstrip("."))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def parse_subject(subject: str) -> list[Terms]:
    """Read every action and its terms out of one subject.

    Each is a type, a qualifier naming the kind of dividend, the share count before and after, and
    a dividend amount. A subject naming an action whose terms it does not carry reads as one
    `unhandled` action, and one naming no action at all reads as none.
    """
    text = " ".join(subject.split())
    found: list[Terms] = []

    for match in BONUS.finditer(text):
        received, held = _number(match.group(1)), _number(match.group(2))
        if received and held:
            found.append(("bonus", DEFAULT_QUALIFIER, held, held + received, None))

    for match in FACE_VALUE_CHANGE.finditer(text):
        old_face, new_face = _number(match.group(2)), _number(match.group(3))
        if not (old_face and new_face) or old_face == new_face:
            continue
        if new_face > old_face:
            found.append(
                ("consolidation", DEFAULT_QUALIFIER, new_face / old_face, Decimal(1), None)
            )
        else:
            found.append(("split", DEFAULT_QUALIFIER, Decimal(1), old_face / new_face, None))

    for match in DIVIDEND.finditer(text):
        amount = _number(match.group(2))
        if amount:
            kind = (match.group(1) or DEFAULT_QUALIFIER).lower()
            found.append(("dividend", kind, None, None, amount))

    unhandled: Terms = ("unhandled", text.lower()[:QUALIFIER_LIMIT], None, None, None)
    if found:
        if UNSTATED_DIVIDEND.search(text) and not any(item[0] == "dividend" for item in found):
            found.append(unhandled)
        return found
    if NOTICE.search(text) or text.strip("-. ").lower() in EMPTY_SUBJECTS:
        return []
    return [unhandled]


def parse_actions(payload: bytes) -> tuple[dict[str, str], ...]:
    """Read the response into raw records, performing no interpretation."""
    try:
        document = json.loads(decoded(payload, "nse corporate actions"))
    except json.JSONDecodeError as error:
        raise SchemaDrift("nse corporate actions response is not json") from error
    if not isinstance(document, list):
        raise SchemaDrift("nse corporate actions response is not a list")

    for entry in document:
        missing = REQUIRED_FIELDS - set(entry)
        if missing:
            raise SchemaDrift(f"nse corporate action is missing {sorted(missing)}")

    return tuple(document)


def normalize(
    records: Sequence[dict[str, str]], isin_now: dict[str, str], as_of_date: date
) -> tuple[CorporateActionRecord, ...]:
    """Map raw equity records onto canonical actions, under the ISIN each instrument carries now.

    `isin_now` maps every ISIN held to the one it has become, itself where it has not changed. A
    record naming an ISIN outside it is left out and counted.
    """
    equity = EQUITY_SERIES["NSE"]
    actions: list[CorporateActionRecord] = []
    seen: set[tuple[str, str, date, str]] = set()
    outside: set[str] = set()

    for record in records:
        if record["series"] not in equity:
            continue
        isin = isin_now.get(record["isin"])
        if isin is None:
            outside.add(record["isin"])
            continue
        ex_date = datetime.strptime(record["exDate"], EX_DATE_FORMAT).date()  # noqa: DTZ007
        subject = " ".join(record["subject"].split())

        for action_type, qualifier, ratio_from, ratio_to, amount in parse_subject(subject):
            seal = (isin, action_type, ex_date, qualifier)
            if seal in seen:
                continue
            seen.add(seal)
            actions.append(
                CorporateActionRecord(
                    isin=isin,
                    action_type=action_type,
                    ex_date=ex_date,
                    source_id=SOURCE_ID,
                    as_of_date=as_of_date,
                    qualifier=qualifier,
                    ratio_from=ratio_from,
                    ratio_to=ratio_to,
                    dividend_amount=amount,
                    purpose=subject if action_type == "unhandled" else None,
                )
            )

    if outside:
        logger.info(
            "nse corporate actions for instruments outside the tracked universe",
            extra={"source_id": SOURCE_ID, "isins": len(outside), "kept": len(actions)},
        )
    return tuple(actions)


def years(collected_on: date) -> list[tuple[date, date]]:
    """Every calendar year of ex-dates the venue has recorded or announced."""
    return calendar_years(FIRST_YEAR, collected_on)


class NseCorporateActions:
    """Reads every action the venue recorded with an ex-date inside a range, for every security."""

    source_id = SOURCE_ID

    def __init__(self, client: ThrottledClient, cache: DiskCache, base_url: str) -> None:
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")
        self._holds_cookie = False

    def url_for(self, first: date, last: date) -> str:
        return (
            f"{self._base_url}/corporates-corporateActions?index=equities"
            f"&from_date={first:%d-%m-%Y}&to_date={last:%d-%m-%Y}"
        )

    def fetch(self, first: date, last: date, collected_on: date) -> bytes:
        key = range_key(first, last, collected_on)
        cached = self._cache.read(SOURCE_ID, key, CACHE_SUFFIX)
        if cached is not None:
            return cached

        payload = self._read(self.url_for(first, last))
        # A response that is not the answer, such as a page served in its place, is never held.
        parse_actions(payload)
        self._cache.write(SOURCE_ID, key, CACHE_SUFFIX, payload)
        return payload

    def parse(self, payload: bytes) -> tuple[dict[str, str], ...]:
        return parse_actions(payload)

    def normalize(
        self, records: Sequence[dict[str, str]], isin_now: dict[str, str], as_of_date: date
    ) -> tuple[CorporateActionRecord, ...]:
        return normalize(records, isin_now, as_of_date)

    def _read(self, url: str) -> bytes:
        self._obtain_cookie()
        try:
            return self._client.get(url, REQUIRED_HEADERS)
        except SourceUnavailable:
            self._holds_cookie = False
            self._obtain_cookie()
            return self._client.get(url, REQUIRED_HEADERS)

    def _obtain_cookie(self) -> None:
        if self._holds_cookie:
            return
        self._client.get(FILINGS_PAGE)
        self._holds_cookie = True
