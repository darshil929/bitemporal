"""Every corporate action BSE has recorded against the instruments it lists.

The venue answers per scrip code with that code's whole history, so a run walks scrip codes rather
than days. A code whose instrument changed face value is read first, since a series cannot be drawn
across a split until the split is known, and each code is committed as it is read, so a run that
stops part way keeps what it reached.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.facts import persist_actions, record_ingestion
from pipelines.resources import CorporateActions, Database
from pipelines.sources.errors import SourceError

GROUP = "ingestion"

# Both venues name their trading days in Indian time, and a collection date is one of those days.
VENUE_TIME = ZoneInfo("Asia/Kolkata")

# Each BSE scrip code with the ISIN it trades under now. A code that changed face value has carried
# more than one ISIN, and its actions belong to the current one, which the lineage maps every
# earlier ISIN onto.
SCRIP_CODES = """
select
    current_listing.scrip_code,
    current_listing.isin,
    exists (
        select 1 from instrument_succession succession
        where succession.exchange = 'BSE'
          and succession.successor_isin = current_listing.isin
    ) as changed_face_value
from (
    select distinct on (scrip_code) scrip_code, isin
    from listing
    where exchange = 'BSE' and scrip_code is not null
    order by scrip_code, listing_date desc
) as current_listing
order by changed_face_value desc, current_listing.scrip_code
"""


@asset(
    deps=[AssetKey("instrument_identity")],
    group_name=GROUP,
    description="Corporate actions for every BSE scrip code, those that changed face value first.",
)
def corporate_actions(
    context: AssetExecutionContext, database: Database, actions: CorporateActions
) -> MaterializeResult[None]:
    definition = actions.definition()
    adapter = actions.adapter()
    collected_on = datetime.now(VENUE_TIME).date()
    version = definition.version_for(collected_on)

    read = failed = written = changed_face_value = 0

    with database.connect() as connection:
        codes = connection.execute(SCRIP_CODES).fetchall()

        for scrip_code, isin, has_changed in codes:
            try:
                records = adapter.normalize(
                    adapter.parse(adapter.fetch(scrip_code)), {scrip_code: isin}, collected_on
                )
            except SourceError as failure:
                record_ingestion(
                    connection,
                    definition.source_id,
                    scrip_code,
                    version,
                    "failed",
                    detail=str(failure),
                )
                connection.commit()
                failed += 1
                context.log.warning(
                    "corporate actions could not be read",
                    extra={"scrip_code": scrip_code, "detail": str(failure)},
                )
                continue

            written += persist_actions(connection, records)
            record_ingestion(
                connection, definition.source_id, scrip_code, version, "succeeded", len(records)
            )
            connection.commit()

            read += 1
            changed_face_value += int(has_changed)

    context.log.info(
        "corporate actions ingested",
        extra={"scrip_codes": read, "failed": failed, "written": written},
    )
    return MaterializeResult(
        metadata={
            "scrip_codes": read,
            "changed_face_value": changed_face_value,
            "failed": failed,
            "written": written,
            "collected_on": collected_on.isoformat(),
        }
    )
