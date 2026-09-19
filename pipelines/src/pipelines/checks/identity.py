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


# A superseded stretch is one the instrument traded on past, under a new ISIN. Without the link
# the series stops there, and the bars before it belong to nothing a reader can reach.
SUPERSEDED_WITHOUT_A_SUCCESSOR = """
select count(*)
from listing l
where l.closure_reason = 'superseded'
  and not exists (
    select 1 from instrument_succession s
    where s.predecessor_isin = l.isin and s.exchange = l.exchange
)
"""

SUCCESSOR_NEVER_TRADED = """
select count(*)
from instrument_succession s
where not exists (
    select 1 from listing l
    where l.isin = s.successor_isin
      and l.exchange = s.exchange
      and l.listing_date = s.changed_on
)
"""


@asset_check(
    asset=instrument_identity,
    blocking=True,
    description="Every superseded listing has a successor.",
)
def every_superseded_listing_names_its_successor(
    context: AssetCheckExecutionContext, database: Database
) -> AssetCheckResult:
    with database.connect() as connection:
        unlinked = connection.execute(SUPERSEDED_WITHOUT_A_SUCCESSOR).fetchone()
        untraded = connection.execute(SUCCESSOR_NEVER_TRADED).fetchone()

    missing = int(unlinked[0]) if unlinked else 0
    absent = int(untraded[0]) if untraded else 0

    return AssetCheckResult(
        passed=missing == 0 and absent == 0,
        metadata={
            "superseded_without_a_successor": missing,
            "successors_that_never_traded": absent,
        },
        description=(
            "Every listing closed by a change of ISIN names the ISIN that took it over, and each "
            "successor opened a listing at that venue on the day it took over."
        ),
    )
