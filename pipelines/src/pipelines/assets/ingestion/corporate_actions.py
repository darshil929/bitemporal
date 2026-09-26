"""Every corporate action BSE has recorded, read a calendar year of ex-dates at a time.

The venue answers a range of ex-dates with the actions of every scrip code inside it, so a run
walks years rather than scrip codes, and each year is committed as it is read. A year's answer must
hold every action already stored for that year: a range the venue cut short reads the same as a
year with fewer actions in it.
"""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

import psycopg
from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.facts import persist_actions, record_ingestion
from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.resources import CorporateActions, Database
from pipelines.sources.bse.corporate_actions import years
from pipelines.sources.errors import SchemaDrift, SourceError
from pipelines.sources.registry import SourceDefinition

GROUP = "ingestion"

# Both venues name their trading days in Indian time, and a collection date is one of those days.
VENUE_TIME = ZoneInfo("Asia/Kolkata")

# Each BSE scrip code with the ISIN it trades under now. A code that changed face value has carried
# more than one ISIN, and its actions belong to the current one, which the lineage maps every
# earlier ISIN onto.
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

# The latest version of every action already stored for a range.
HELD = """
select distinct on (isin, action_type, ex_date, qualifier)
    isin, action_type, ex_date, qualifier, ratio_from, ratio_to, dividend_amount, purpose
from corporate_action
where source_id = %s and ex_date between %s and %s
order by isin, action_type, ex_date, qualifier, as_of_date desc
"""

type ActionKey = tuple[str, str, date, str]
type Terms = tuple[Decimal | None, Decimal | None, Decimal | None, str | None]


def held_actions(
    connection: psycopg.Connection, source_id: str, first: date, last: date, current: dict[str, str]
) -> dict[ActionKey, Terms]:
    """Actions already stored for the range, each under the ISIN its scrip code carries now."""
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


def key_of(item: CorporateActionRecord) -> ActionKey:
    return (item.isin, item.action_type, item.ex_date, item.qualifier)


def terms_of(item: CorporateActionRecord) -> Terms:
    return (item.ratio_from, item.ratio_to, item.dividend_amount, item.purpose)


class RangeReader(Protocol):
    def fetch(self, first: date, last: date, collected_on: date) -> bytes: ...

    def parse(self, payload: bytes) -> tuple[dict[str, str], ...]: ...

    def normalize(
        self, records: Sequence[dict[str, str]], mapping: dict[str, str], as_of_date: date
    ) -> tuple[CorporateActionRecord, ...]: ...


def collect_ranges(
    context: AssetExecutionContext,
    connection: psycopg.Connection,
    definition: SourceDefinition,
    adapter: RangeReader,
    ranges: list[tuple[date, date]],
    collected_on: date,
    mapping: dict[str, str],
    current: dict[str, str],
) -> MaterializeResult[None]:
    """Read each range of ex-dates, committing each as it is read.

    `mapping` resolves a row to an ISIN in the venue adapter's terms, and `current` maps every ISIN
    already stored onto the one it has since become.
    """
    version = definition.version_for(collected_on)
    read = failed = written = 0

    for first, last in ranges:
        partition = f"{first:%Y%m%d}-{last:%Y%m%d}"
        try:
            records = adapter.normalize(
                adapter.parse(adapter.fetch(first, last, collected_on)), mapping, collected_on
            )
            outside = sorted(
                {item.ex_date for item in records if not first <= item.ex_date <= last}
            )
            if outside:
                raise SchemaDrift(f"answer for {partition} holds ex-dates {outside[:3]} outside it")
            held = held_actions(connection, definition.source_id, first, last, current)
            missing = held.keys() - {key_of(item) for item in records}
            if missing:
                raise SchemaDrift(
                    f"answer for {partition} lacks {len(missing)} actions already stored,"
                    f" such as {sorted(missing)[:3]}"
                )
        except SourceError as failure:
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

        # An action stored with the same terms is not new information, so only an action the
        # venue reports for the first time, or restates, becomes a further version.
        fresh = tuple(item for item in records if held.get(key_of(item)) != terms_of(item))
        written += persist_actions(connection, fresh)
        record_ingestion(
            connection, definition.source_id, partition, version, "succeeded", len(records)
        )
        connection.commit()
        read += 1

    context.log.info(
        "corporate actions ingested",
        extra={
            "source_id": definition.source_id,
            "ranges": read,
            "failed": failed,
            "written": written,
        },
    )
    return MaterializeResult(
        metadata={
            "ranges": read,
            "failed": failed,
            "written": written,
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
        isin_for_scrip = dict(connection.execute(SCRIP_CODES).fetchall())
        current = {isin: isin_for_scrip[code] for isin, code in connection.execute(LISTED)}
        return collect_ranges(
            context,
            connection,
            actions.definition(),
            actions.adapter(),
            ranges,
            collected_on,
            isin_for_scrip,
            current,
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
