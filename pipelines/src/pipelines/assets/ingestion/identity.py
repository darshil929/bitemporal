"""Who traded where, rebuilt from every bar stored rather than from the day just read.

A listing stretch and a primary venue designation both read years of bars, so neither can be
derived one partition at a time. This runs after ingestion over the whole history, which also
makes it indifferent to the order a backfill filled the days in.
"""

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from pipelines.history import read_stretches, read_turnover, venue_last_days
from pipelines.identity import close_listings, derive_primary_venue, persist_identity
from pipelines.resources import Database

GROUP = "ingestion"

BHAVCOPIES = [AssetKey("bse_bhavcopy"), AssetKey("nse_bhavcopy")]


@asset(
    deps=BHAVCOPIES,
    group_name=GROUP,
    description="Listing stretches and the primary venue, derived from every stored bar.",
)
def instrument_identity(
    context: AssetExecutionContext, database: Database
) -> MaterializeResult[None]:
    with database.connect() as connection:
        stretches = read_stretches(connection)
        listings = close_listings(stretches, venue_last_days(connection))
        venues = derive_primary_venue(read_turnover(connection))

        persist_identity(connection, (), listings, venues)
        connection.commit()

    closed = sum(1 for listing in listings if listing.closure_reason)
    context.log.info(
        "identity derived",
        extra={"listings": len(listings), "closed": closed, "designations": len(venues)},
    )
    return MaterializeResult(
        metadata={
            "listings": len(listings),
            "closed": closed,
            "superseded": sum(1 for item in listings if item.closure_reason == "superseded"),
            "designations": len(venues),
            "instruments": len({listing.isin for listing in listings}),
        }
    )
