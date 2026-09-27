"""The one calendar of days every ingestion asset is partitioned by.

Dagster runs assets in one job only where they share a partitions definition, so both venues'
prices and delivery take the same days: from the first day either venue's prices are registered
for, in India Standard Time. A source passes over a day it does not cover without a request.
"""

from collections.abc import Iterator
from datetime import date, timedelta

from dagster import TimeWindowPartitionsDefinition

from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.resources import BHAVCOPY_SOURCES
from pipelines.sources.registry import load_definitions

# Every day, since a session is not confined to the weekdays.
EVERY_DAY = "0 0 * * *"


def first_priced_day() -> date:
    """The first day either venue's prices are registered for."""
    priced = [item for item in load_definitions() if item.source_id in BHAVCOPY_SOURCES.values()]
    return min(version.effective_from for item in priced for version in item.schema_version)


# Both venues publish a day's files the same evening, so today is a partition.
INGESTION_DAYS = TimeWindowPartitionsDefinition(
    cron_schedule=EVERY_DAY,
    start=f"{first_priced_day():%Y-%m-%d}",
    fmt="%Y-%m-%d",
    timezone=VENUE_TIME.key,
    end_offset=1,
)


def calendar_days(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)
