"""Instrument names from the exchanges' lists of securities, read once a day by both flows.

A list carries no date a name was given, so a name is dated the day the list was read. A name is
written when a list first gives it or changes it; one unchanged since the last read is not written
again.
"""

from collections import defaultdict
from datetime import date, datetime

import psycopg
from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.facts import persist_names, record_ingestion
from pipelines.models.identity import InstrumentNameRecord
from pipelines.resources import Database, ScripLists
from pipelines.sources.bse.scrip_list import STATUSES, ScripListing, names_by_isin
from pipelines.sources.errors import SourceError

GROUP = "ingestion"

HELD_BSE_CODES = """
select isin, scrip_code from listing where exchange = 'BSE' and scrip_code is not null
"""

LATEST_NAMES = """
select distinct on (isin) isin, name
from instrument_name
where source_id = %s
order by isin, as_of_date desc
"""


def held_bse_codes(connection: psycopg.Connection) -> dict[str, set[str]]:
    codes: dict[str, set[str]] = defaultdict(set)
    for isin, code in connection.execute(HELD_BSE_CODES):
        codes[isin].add(code)
    return dict(codes)


def fresh_names(
    connection: psycopg.Connection, source_id: str, names: dict[str, str], collected_on: date
) -> list[InstrumentNameRecord]:
    """The names given to instruments held here that differ from the latest stored for them."""
    held = {isin for (isin,) in connection.execute("select isin from instrument_master")}
    latest: dict[str, str] = dict(connection.execute(LATEST_NAMES, (source_id,)).fetchall())
    return [
        InstrumentNameRecord(isin=isin, source_id=source_id, as_of_date=collected_on, name=name)
        for isin, name in sorted(names.items())
        if isin in held and latest.get(isin) != name
    ]


def ingest_bse_names(
    context: AssetExecutionContext,
    database: Database,
    lists: ScripLists,
    collected_on: date,
) -> MaterializeResult[None]:
    source_id = lists.definition().source_id
    version = lists.definition().version_for(collected_on)
    adapter = lists.adapter()
    listings: list[ScripListing] = []
    failed = written = 0

    with database.connect() as connection:
        for status in STATUSES:
            partition = f"{status.lower()}-{collected_on:%Y%m%d}"
            try:
                read = adapter.parse(adapter.fetch(status, collected_on), status)
            except SourceError as failure:
                failed += 1
                record_ingestion(
                    connection, source_id, partition, version, "failed", None, str(failure)
                )
                context.log.warning(
                    "list of scrips could not be read",
                    extra={"status": status, "detail": str(failure)},
                )
            else:
                record_ingestion(connection, source_id, partition, version, "succeeded", len(read))
                listings.extend(read)
            connection.commit()

        # An ISIN a later status names is otherwise named from an earlier one, so a list read in
        # part names nothing.
        if not failed:
            names = names_by_isin(listings, held_bse_codes(connection))
            written = persist_names(
                connection, fresh_names(connection, source_id, names, collected_on)
            )
            connection.commit()

    context.log.info(
        "instrument names read",
        extra={"source_id": source_id, "failed": failed, "written": written},
    )
    return MaterializeResult(
        metadata={
            "lists": len(STATUSES) - failed,
            "failed": failed,
            "written": written,
            "collected_on": collected_on.isoformat(),
        }
    )


@asset(
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="Instrument names from BSE's list of scrips, active, suspended and delisted.",
)
def bse_instrument_names(
    context: AssetExecutionContext, database: Database, scrip_lists: ScripLists
) -> MaterializeResult[None]:
    return ingest_bse_names(context, database, scrip_lists, datetime.now(VENUE_TIME).date())
