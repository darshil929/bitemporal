"""The daily sync's schedule, stopped until a deployment starts it."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from dagster import DefaultScheduleStatus, RunRequest, build_schedule_context

from pipelines.definitions import defs
from pipelines.jobs import RANGE_END, RANGE_START
from pipelines.schedules import daily_sync_schedule

INDIA = ZoneInfo("Asia/Kolkata")


def test_the_daily_sync_runs_each_evening_and_morning_in_india_and_starts_stopped() -> None:
    scheduled = defs.resolve_schedule_def("daily_sync_schedule")

    assert scheduled.job_name == "daily_sync"
    assert scheduled.cron_schedule == ["30 20 * * *", "30 7 * * *"]
    assert scheduled.execution_timezone == "Asia/Kolkata"
    assert scheduled.default_status == DefaultScheduleStatus.STOPPED


@pytest.mark.parametrize(
    ("scheduled_at", "first", "last"),
    [
        (datetime(2026, 9, 28, 20, 30, tzinfo=INDIA), "2026-09-22", "2026-09-28"),
        (datetime(2026, 9, 29, 7, 30, tzinfo=INDIA), "2026-09-23", "2026-09-29"),
    ],
)
def test_a_scheduled_sync_reads_the_seven_days_ending_that_day_in_india(
    scheduled_at: datetime, first: str, last: str
) -> None:
    """A file published after the evening's run is read the next morning."""
    request = daily_sync_schedule(build_schedule_context(scheduled_execution_time=scheduled_at))

    assert isinstance(request, RunRequest)
    assert request.tags[RANGE_START] == first
    assert request.tags[RANGE_END] == last
