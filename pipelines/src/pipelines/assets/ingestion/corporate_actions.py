"""Every corporate action BSE has recorded, read a calendar year of ex-dates at a time.

The venue answers a range of ex-dates with the actions of every scrip code inside it, so a run
walks years rather than scrip codes, and each year is committed as it is read. A year's answer
should hold every action already stored for that year of an instrument the venue still trades: a
range the venue cut short reads the same as a year with fewer actions in it. Such an answer fails its
year, yet the actions it holds are stored, since an action stored before is never removed and an
absence decides nothing; an answer for a year still open is set aside, so the next run asks again.
"""

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

import psycopg
from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.facts import persist_actions, record_ingestion
from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.resources import CorporateActions, Database
from pipelines.sources.bse.corporate_actions import ScripResolver, Stretch, years
from pipelines.sources.errors import SchemaDrift, SourceError
from pipelines.sources.registry import SourceDefinition

GROUP = "ingestion"

# Both venues name their trading days in Indian time, and a collection date is one of those days.
VENUE_TIME = ZoneInfo("Asia/Kolkata")

# Each BSE scrip code with the ISIN it was last listed under.
SCRIP_CODES = """
select distinct on (scrip_code) scrip_code, isin
from listing
where exchange = 'BSE' and scrip_code is not null
order by scrip_code, listing_date desc
"""

# Every ISIN a BSE scrip code has carried.
LISTED = """
select distinct isin, scrip_code
from listing
where exchange = 'BSE' and scrip_code is not null
"""

# Each BSE scrip code with the ISINs it has been listed under and when.
STRETCHES = """
select scrip_code, listing_date, delisting_date, isin
from listing
where exchange = 'BSE' and scrip_code is not null
order by scrip_code, listing_date
"""

# Successions at NSE first, since the venue's own records name its ISINs, then at BSE.
SUCCESSIONS = """
select predecessor_isin, successor_isin
from instrument_succession
order by case exchange when 'NSE' then 0 else 1 end
"""

# The latest version of every action already stored for a range.
LATEST = """
select distinct on (isin, action_type, ex_date, qualifier)
    isin, action_type, ex_date, qualifier, ratio_from, ratio_to, dividend_amount, purpose,
    is_withdrawn
from corporate_action
where source_id = %s and ex_date between %s and %s
order by isin, action_type, ex_date, qualifier, as_of_date desc
"""
# Those latest versions, a withdrawn text left out.
HELD = f"""
select isin, action_type, ex_date, qualifier, ratio_from, ratio_to, dividend_amount, purpose
from ({LATEST}) as latest
where not is_withdrawn
"""

# Each instrument with a bar at a venue over a range of trading days.
TRADED = """
select distinct isin
from price_daily
where venue = %s and trade_date >= %s and trade_date < %s
"""

# A venue's answer leaves out every action of an instrument that has left the venue, as after an
# amalgamation. An instrument without a bar at the venue over these days before collection has left.
UNTRADED_DAYS = 30

UNHANDLED = "unhandled"

type ActionKey = tuple[str, str, date, str]
type Terms = tuple[Decimal | None, Decimal | None, Decimal | None, str | None]


def isins_now(connection: psycopg.Connection) -> dict[str, str]:
    """Every ISIN held, mapped onto the one it trades under now, itself where it never changed."""
    successor: dict[str, str] = {}
    for predecessor, following in connection.execute(SUCCESSIONS):
        successor.setdefault(predecessor, following)

    mapping = {}
    for (isin,) in connection.execute("select isin from instrument_master"):
        now, seen = isin, {isin}
        while now in successor and successor[now] not in seen:
            now = successor[now]
            seen.add(now)
        mapping[isin] = now
    return mapping


def bse_listings(connection: psycopg.Connection) -> dict[str, tuple[Stretch, ...]]:
    listed: dict[str, list[Stretch]] = defaultdict(list)
    for code, first, last, isin in connection.execute(STRETCHES):
        listed[code].append((first, last, isin))
    return {code: tuple(stretches) for code, stretches in listed.items()}


def held_actions(
    connection: psycopg.Connection, source_id: str, first: date, last: date, current: dict[str, str]
) -> dict[ActionKey, Terms]:
    """Actions already stored for the range, each under the ISIN its instrument trades under now."""
    rows = connection.execute(HELD, (source_id, first, last)).fetchall()
    return {
        (str(current.get(isin, isin)), kind, ex_date, qualifier): (
            ratio_from,
            ratio_to,
            amount,
            purpose,
        )
        for isin, kind, ex_date, qualifier, ratio_from, ratio_to, amount, purpose in rows
    }


def traded_at(
    connection: psycopg.Connection, venue: str, collected_on: date, current: dict[str, str]
) -> set[str]:
    """Each instrument the venue traded in the days before collection, under the ISIN it has now."""
    since = collected_on - timedelta(days=UNTRADED_DAYS)
    return {
        str(current.get(isin, isin))
        for (isin,) in connection.execute(TRADED, (venue, since, collected_on))
    }


def named(keys: list[ActionKey]) -> str:
    return ", ".join(
        f"{isin} {kind} {ex_date:%Y-%m-%d} {qualifier}" for isin, kind, ex_date, qualifier in keys
    )


def key_of(item: CorporateActionRecord) -> ActionKey:
    return (item.isin, item.action_type, item.ex_date, item.qualifier)


def answered(
    records: tuple[CorporateActionRecord, ...], listed_as: dict[str, str]
) -> tuple[Callable[[ActionKey], ActionKey], set[ActionKey], set[tuple[str, date]]]:
    """The listing a key stands for, and the actions and instrument days an answer holds by it."""

    def listing(key: ActionKey) -> ActionKey:
        isin, kind, ex_date, qualifier = key
        return (listed_as.get(isin, isin), kind, ex_date, qualifier)

    held_in_answer = {listing(key_of(item)) for item in records}
    return listing, held_in_answer, {(key[0], key[2]) for key in held_in_answer}


def unanswered(
    held: dict[ActionKey, Terms],
    records: tuple[CorporateActionRecord, ...],
    listed_as: dict[str, str],
) -> list[ActionKey]:
    """Actions already stored that an answer does not account for.

    `listed_as` maps each ISIN onto one standing for the venue-local identifier it was listed
    under, so an action placed under another ISIN since it was stored is still recognised.

    An action held as unhandled is the venue's text with no terms read from it. A parser that has
    since learned to read that text answers it with the terms instead, so any action the answer
    holds for the same instrument on the same ex-date accounts for it.
    """
    listing, held_in_answer, days = answered(records, listed_as)
    return sorted(
        key
        for key in held
        if listing(key) not in held_in_answer
        and not (key[1] == UNHANDLED and (listing(key)[0], key[2]) in days)
    )


def read_days(held: dict[ActionKey, Terms], listed_as: dict[str, str]) -> set[tuple[str, date]]:
    """The instrument days already holding an action read with terms, by listing."""
    return {(listed_as.get(key[0], key[0]), key[2]) for key in held if key[1] != UNHANDLED}


def replaced_texts(
    held: dict[ActionKey, Terms],
    records: tuple[CorporateActionRecord, ...],
    listed_as: dict[str, str],
) -> set[ActionKey]:
    """Actions held as unhandled that an answer replaces with others for the same day.

    The answer no longer holds the text and holds other actions for that instrument and ex-date: a
    parser that has learned the text's wording reads its terms, or the venue has restated it.
    """
    listing, held_in_answer, days = answered(records, listed_as)
    return {
        key
        for key in held
        if key[1] == UNHANDLED
        and listing(key) not in held_in_answer
        and (listing(key)[0], key[2]) in days
    }


def withdrawals(
    connection: psycopg.Connection,
    source_id: str,
    first: date,
    last: date,
    current: dict[str, str],
    replaced: set[ActionKey],
    collected_on: date,
) -> tuple[CorporateActionRecord, ...]:
    """A withdrawn version of each replaced text, under the ISIN it was stored under."""
    if not replaced:
        return ()
    rows = connection.execute(HELD, (source_id, first, last)).fetchall()
    return tuple(
        CorporateActionRecord(
            isin=isin,
            action_type=kind,
            ex_date=ex_date,
            source_id=source_id,
            as_of_date=collected_on,
            qualifier=qualifier,
            purpose=purpose,
            is_withdrawn=True,
        )
        for isin, kind, ex_date, qualifier, _, _, _, purpose in rows
        if (current.get(isin, isin), kind, ex_date, qualifier) in replaced
    )


def terms_of(item: CorporateActionRecord) -> Terms:
    return (item.ratio_from, item.ratio_to, item.dividend_amount, item.purpose)


class RangeReader(Protocol):
    def fetch(self, first: date, last: date, collected_on: date) -> bytes: ...

    def set_aside(self, first: date, last: date, collected_on: date) -> None: ...

    def parse(self, payload: bytes) -> tuple[dict[str, str], ...]: ...


type Normalize = Callable[[tuple[dict[str, str], ...]], tuple[CorporateActionRecord, ...]]


def collect_ranges(
    context: AssetExecutionContext,
    connection: psycopg.Connection,
    definition: SourceDefinition,
    venue: str,
    adapter: RangeReader,
    ranges: list[tuple[date, date]],
    collected_on: date,
    normalize: Normalize,
    current: dict[str, str],
    listed_as: dict[str, str],
) -> MaterializeResult[None]:
    """Read each range of ex-dates, committing each as it is read.

    `normalize` turns a venue's response into actions under the ISINs they belong to, `current`
    maps every ISIN already stored onto the one it has since become, and `listed_as` onto one
    standing for the venue-local identifier it was listed under. A stored action the answer lacks
    fails its range unless the venue has stopped trading the instrument, and is then excused; the
    actions a failed answer holds are stored all the same, and nothing is withdrawn on its word. A
    stored text a complete answer replaces with other actions for its day is withdrawn.
    """
    version = definition.version_for(collected_on)
    trading = traded_at(connection, venue, collected_on, current)
    read = failed = written = excused = withdrawn = 0

    for first, last in ranges:
        partition = f"{first:%Y%m%d}-{last:%Y%m%d}"
        try:
            records = normalize(adapter.parse(adapter.fetch(first, last, collected_on)))
            outside = sorted(
                {item.ex_date for item in records if not first <= item.ex_date <= last}
            )
            if outside:
                raise SchemaDrift(f"answer for {partition} holds ex-dates {outside[:3]} outside it")
            held = held_actions(connection, definition.source_id, first, last, current)
        except SourceError as failure:
            adapter.set_aside(first, last, collected_on)
            record_ingestion(
                connection, definition.source_id, partition, version, "failed", detail=str(failure)
            )
            connection.commit()
            failed += 1
            context.log.warning(
                "corporate actions could not be read",
                extra={
                    "source_id": definition.source_id,
                    "range": partition,
                    "detail": str(failure),
                },
            )
            continue

        missing = unanswered(held, records, listed_as)
        refused = [key for key in missing if key[0] in trading]
        # An action stored with the same terms is not new information, so only an action the
        # venue reports for the first time, or restates, becomes a further version.
        fresh = tuple(item for item in records if held.get(key_of(item)) != terms_of(item))
        if refused:
            # A short answer can carry again a text a complete answer has since read with terms.
            with_terms = read_days(held, listed_as)
            fresh = tuple(
                item
                for item in fresh
                if item.action_type != UNHANDLED
                or (listed_as.get(item.isin, item.isin), item.ex_date) not in with_terms
            )
            stored = persist_actions(connection, fresh)
            refusal = (
                f"answer for {partition} lacks {len(refused)} actions already stored,"
                f" such as {refused[:3]}; stored {stored} new or restated actions it holds"
            )
            record_ingestion(
                connection, definition.source_id, partition, version, "failed", detail=refusal
            )
            connection.commit()
            adapter.set_aside(first, last, collected_on)
            written += stored
            failed += 1
            context.log.warning(
                "corporate actions answer lacks actions already stored",
                extra={"source_id": definition.source_id, "range": partition, "detail": refusal},
            )
            continue
        replaced = replaced_texts(held, records, listed_as)
        withdrawn_now = withdrawals(
            connection, definition.source_id, first, last, current, replaced, collected_on
        )
        # A version already stored under the same day is not written again, so a withdrawal counts
        # only once written.
        withdrawn_written = persist_actions(connection, withdrawn_now)
        written += persist_actions(connection, fresh) + withdrawn_written
        withdrawn += withdrawn_written
        detail = (
            f"lacks {len(missing)} actions of instruments untraded at {venue} for"
            f" {UNTRADED_DAYS} days: {named(missing)}"
            if missing
            else None
        )
        record_ingestion(
            connection,
            definition.source_id,
            partition,
            version,
            "succeeded",
            len(records),
            detail=detail,
        )
        connection.commit()
        read += 1
        excused += len(missing)
        if missing:
            context.log.info(
                "stored corporate actions absent from the answer for instruments no longer traded",
                extra={
                    "source_id": definition.source_id,
                    "range": partition,
                    "count": len(missing),
                    "actions": named(missing[:5]),
                },
            )
        if withdrawn_written:
            context.log.info(
                "stored corporate action texts withdrawn, replaced by the answer",
                extra={
                    "source_id": definition.source_id,
                    "range": partition,
                    "count": withdrawn_written,
                    "actions": named(sorted(replaced)[:5]),
                },
            )

    context.log.info(
        "corporate actions ingested",
        extra={
            "source_id": definition.source_id,
            "ranges": read,
            "failed": failed,
            "written": written,
            "excused": excused,
            "withdrawn": withdrawn,
        },
    )
    return MaterializeResult(
        metadata={
            "ranges": read,
            "failed": failed,
            "written": written,
            "excused": excused,
            "withdrawn": withdrawn,
            "collected_on": collected_on.isoformat(),
        }
    )


def ingest_actions(
    context: AssetExecutionContext,
    database: Database,
    actions: CorporateActions,
    ranges: list[tuple[date, date]],
    collected_on: date,
) -> MaterializeResult[None]:
    with database.connect() as connection:
        current = isins_now(connection)
        resolver = ScripResolver(bse_listings(connection), current)
        last_listed = dict(connection.execute(SCRIP_CODES).fetchall())
        listed_as = {isin: last_listed[code] for isin, code in connection.execute(LISTED)}
        adapter = actions.adapter()
        return collect_ranges(
            context,
            connection,
            actions.definition(),
            "BSE",
            adapter,
            ranges,
            collected_on,
            lambda rows: adapter.normalize(rows, resolver, collected_on),
            current,
            listed_as,
        )


@asset(
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="Corporate actions for every BSE scrip code, a calendar year of ex-dates at a time.",
)
def corporate_actions(
    context: AssetExecutionContext, database: Database, actions: CorporateActions
) -> MaterializeResult[None]:
    collected_on = datetime.now(VENUE_TIME).date()
    return ingest_actions(context, database, actions, years(collected_on), collected_on)
