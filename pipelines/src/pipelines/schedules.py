"""When the daily sync runs: each evening once both venues have published, and each morning.

Both runs read the seven days ending that day in India, so a file published after the evening run
is read the next morning. The schedule is stopped until a deployment starts it.
"""

from dagster import (
    DefaultScheduleStatus,
    RunRequest,
    ScheduleEvaluationContext,
    schedule,
)

from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.jobs import RANGE_END, RANGE_START, daily_sync, sync_window

EVENING_AND_MORNING = ["30 20 * * *", "30 7 * * *"]


@schedule(
    job=daily_sync,
    cron_schedule=EVENING_AND_MORNING,
    execution_timezone=VENUE_TIME.key,
    default_status=DefaultScheduleStatus.STOPPED,
    description="The daily sync at 20:30 and 07:30 in India, over the seven days ending that day.",
)
def daily_sync_schedule(context: ScheduleEvaluationContext) -> RunRequest:
    day = context.scheduled_execution_time.astimezone(VENUE_TIME).date()
    first, last = sync_window(day)
    return RunRequest(tags={RANGE_START: first.isoformat(), RANGE_END: last.isoformat()})
