"""The two flows a deployment runs: a history bootstrap and a daily sync.

Both run every asset over a range of days, given by Dagster's partition range tags, and carry the
flow's name in a tag, by which a run of either is found and one flow is held to at a time.
"""

from datetime import date, timedelta

from dagster import AssetSelection, define_asset_job

FLOW_TAG = "bitemporal/flow"
BOOTSTRAP = "bootstrap"
SYNC = "sync"

RANGE_START = "dagster/asset_partition_range_start"
RANGE_END = "dagster/asset_partition_range_end"

# A file published late, or not yet, is asked for again by the syncs of the following week.
SYNC_DAYS = 7

history_bootstrap = define_asset_job(
    "history_bootstrap",
    selection=AssetSelection.all(),
    tags={FLOW_TAG: BOOTSTRAP},
    description="Loads the history of a new installation, a range of days at a time.",
)

daily_sync = define_asset_job(
    "daily_sync",
    selection=AssetSelection.all(),
    tags={FLOW_TAG: SYNC},
    description="Brings an installation up to date over the days ending on a given day.",
)


def sync_window(day: date) -> tuple[date, date]:
    return day - timedelta(days=SYNC_DAYS - 1), day
