"""What identity derivation has to produce before the models downstream may read it."""

from dagster import AssetCheckExecutionContext, AssetCheckResult, asset_check

from pipelines.assets.ingestion.identity import instrument_identity
from pipelines.resources import Database

# A bar outside every stretch has no symbol history behind it, so a rename or a change of ISIN
# around it reads as nothing having happened.
ORPHANED_BARS = """
select count(*)
from price_daily p
where not exists (
    select 1 from listing l
    where l.isin = p.isin
      and l.exchange = p.venue
      and l.listing_date <= p.trade_date
      and (l.delisting_date is null or p.trade_date <= l.delisting_date)
)
"""

STRETCHES_OVERLAP = """
select count(*)
from listing earlier
join listing later
  on later.isin = earlier.isin
 and later.exchange = earlier.exchange
 and coalesce(later.scrip_code, later.local_symbol)
   = coalesce(earlier.scrip_code, earlier.local_symbol)
 and later.listing_date > earlier.listing_date
where earlier.delisting_date is null or later.listing_date <= earlier.delisting_date
"""


@asset_check(asset=instrument_identity, blocking=True, description="Every bar sits in a listing.")
def every_bar_sits_inside_a_listing(
    context: AssetCheckExecutionContext, database: Database
) -> AssetCheckResult:
    with database.connect() as connection:
        orphaned = connection.execute(ORPHANED_BARS).fetchone()
        overlapping = connection.execute(STRETCHES_OVERLAP).fetchone()

    outside = int(orphaned[0]) if orphaned else 0
    overlaps = int(overlapping[0]) if overlapping else 0

    return AssetCheckResult(
        passed=outside == 0 and overlaps == 0,
        metadata={"bars_outside_a_listing": outside, "overlapping_stretches": overlaps},
        description=(
            "Every stored bar falls inside one listing stretch, and no two stretches of the same "
            "venue-local identifier overlap."
        ),
    )
