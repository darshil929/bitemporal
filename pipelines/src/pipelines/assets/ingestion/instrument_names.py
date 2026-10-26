"""Instrument names and face values from the exchanges' lists of securities, read once a day by
both flows.

A list carries no date a name or face value was given, so each is dated the day the list was read.
Each is written when a list first gives it or changes it; one unchanged since the last read is not
written again.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal

import psycopg
from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.facts import persist_face_values, persist_names, record_ingestion
from pipelines.models.identity import InstrumentFaceValueRecord, InstrumentNameRecord
from pipelines.resources import Database, NseLists, ScripLists
from pipelines.sources.bse import scrip_list
from pipelines.sources.errors import SourceError
from pipelines.sources.nse import equity_list
from pipelines.sources.registry import SourceDefinition

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

LATEST_FACE_VALUES = """
select distinct on (isin) isin, face_value
from instrument_face_value
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


def fresh_face_values(
    connection: psycopg.Connection,
    source_id: str,
    face_values: dict[str, Decimal],
    collected_on: date,
) -> list[InstrumentFaceValueRecord]:
    """The face values given to instruments held here that differ from the latest stored."""
    held = {isin for (isin,) in connection.execute("select isin from instrument_master")}
    latest: dict[str, Decimal] = dict(
        connection.execute(LATEST_FACE_VALUES, (source_id,)).fetchall()
    )
    return [
        InstrumentFaceValueRecord(
            isin=isin, source_id=source_id, as_of_date=collected_on, face_value=face_value
        )
        for isin, face_value in sorted(face_values.items())
        if isin in held and latest.get(isin) != face_value
    ]


def ingest_names[T](
    context: AssetExecutionContext,
    database: Database,
    definition: SourceDefinition,
    parts: Sequence[str],
    read: Callable[[str], Sequence[T]],
    choose: Callable[[list[T], psycopg.Connection], dict[str, str]],
    choose_face_values: Callable[[list[T], psycopg.Connection], dict[str, Decimal]],
    collected_on: date,
) -> MaterializeResult[None]:
    """Read every part of a source's list, then write the names and face values drawn from them."""
    source_id = definition.source_id
    version = definition.version_for(collected_on)
    listings: list[T] = []
    failed = written = valued = 0

    with database.connect() as connection:
        for part in parts:
            partition = f"{part.lower()}-{collected_on:%Y%m%d}"
            try:
                listed = read(part)
            except SourceError as failure:
                failed += 1
                record_ingestion(
                    connection, source_id, partition, version, "failed", None, str(failure)
                )
                context.log.warning(
                    "list could not be read",
                    extra={"source_id": source_id, "part": part, "detail": str(failure)},
                )
            else:
                record_ingestion(
                    connection, source_id, partition, version, "succeeded", len(listed)
                )
                listings.extend(listed)
            connection.commit()

        # An ISIN one part names is otherwise named from another, so a list read in part names
        # nothing.
        if not failed:
            names = choose(listings, connection)
            written = persist_names(
                connection, fresh_names(connection, source_id, names, collected_on)
            )
            face_values = choose_face_values(listings, connection)
            valued = persist_face_values(
                connection, fresh_face_values(connection, source_id, face_values, collected_on)
            )
            connection.commit()

    context.log.info(
        "instrument names read",
        extra={
            "source_id": source_id,
            "failed": failed,
            "written": written,
            "face_values": valued,
        },
    )
    return MaterializeResult(
        metadata={
            "lists": len(parts) - failed,
            "failed": failed,
            "written": written,
            "face_values": valued,
            "collected_on": collected_on.isoformat(),
        }
    )


def ingest_bse_names(
    context: AssetExecutionContext, database: Database, lists: ScripLists, collected_on: date
) -> MaterializeResult[None]:
    adapter = lists.adapter()
    return ingest_names(
        context,
        database,
        lists.definition(),
        scrip_list.STATUSES,
        lambda status: adapter.parse(adapter.fetch(status, collected_on), status),
        lambda listings, connection: scrip_list.names_by_isin(listings, held_bse_codes(connection)),
        lambda listings, connection: scrip_list.face_values_by_isin(
            listings, held_bse_codes(connection)
        ),
        collected_on,
    )


def ingest_nse_names(
    context: AssetExecutionContext, database: Database, lists: NseLists, collected_on: date
) -> MaterializeResult[None]:
    adapter = lists.adapter()
    return ingest_names(
        context,
        database,
        lists.definition(),
        tuple(equity_list.BOARDS),
        lambda board: adapter.parse(adapter.fetch(board, collected_on), board),
        lambda listings, _: equity_list.names_by_isin(listings),
        lambda listings, _: equity_list.face_values_by_isin(listings),
        collected_on,
    )


@asset(
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description=(
        "Instrument names and face values from BSE's list of scrips, active, suspended and"
        " delisted."
    ),
)
def bse_instrument_names(
    context: AssetExecutionContext, database: Database, scrip_lists: ScripLists
) -> MaterializeResult[None]:
    return ingest_bse_names(context, database, scrip_lists, datetime.now(VENUE_TIME).date())


@asset(
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description=(
        "Instrument names and face values from NSE's lists of equities, the main board and SME"
        " platform."
    ),
)
def nse_instrument_names(
    context: AssetExecutionContext, database: Database, nse_lists: NseLists
) -> MaterializeResult[None]:
    return ingest_nse_names(context, database, nse_lists, datetime.now(VENUE_TIME).date())
