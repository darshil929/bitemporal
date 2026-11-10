"""The runs of the flows followed while they go and once they end.

A running run's finished steps are copied as they finish; a finished run is recorded with its report;
a request finishes once its last run is recorded; and a bootstrap's older years start once its recent
years finished without a failed step or a cancel, failed days alone not stopping it. Every evaluation
reads the runs as they stand, so one missed while the daemon was down is caught up on the next.
"""

from collections.abc import Sequence
from datetime import date

import psycopg
from dagster import (
    DagsterInstance,
    DefaultSensorStatus,
    RunRequest,
    RunsFilter,
    SensorEvaluationContext,
    SensorResult,
    sensor,
)

from pipelines.flow_requests import request_windows
from pipelines.flows import (
    RECORD_STEP,
    REQUEST_TAG,
    SCHEMA_TAG,
    UNFINISHED,
    record_finished_runs,
    steps_of,
)
from pipelines.jobs import BOOTSTRAP, FLOW_TAG, RANGE_END, RANGE_START, SYNC, history_bootstrap
from pipelines.resources import Database

MONITOR_INTERVAL_SECONDS = 30

STARTED_REQUESTS = """
select id, flow, first_day, last_day, cancel_requested_at from flow_request
where status = 'started'
order by id
"""
NEWEST_RUN = """
select first_day, last_day, outcome, failed_steps from flow_run
where request_id = %s
order by started_at desc
limit 1
"""
FINISH = "update flow_request set status = 'finished', finished_at = now() where id = %s"


def copy_steps(
    instance: DagsterInstance, connection: psycopg.Connection, run_ids: Sequence[str]
) -> None:
    """Copy each run's finished steps that are not yet copied."""
    for run_id in run_ids:
        for step in steps_of(instance.all_logs(run_id)):
            connection.execute(RECORD_STEP, (run_id, *step))
    connection.commit()


def follow_requests(connection: psycopg.Connection) -> list[tuple[int, date, date]]:
    """Finish each started request whose last run is recorded, and return the bootstrap requests
    whose older years are to start, with those days."""
    to_start = []
    for request_id, flow, first_day, last_day, cancel_requested in connection.execute(
        STARTED_REQUESTS
    ).fetchall():
        newest = connection.execute(NEWEST_RUN, (request_id,)).fetchone()
        if newest is None:
            continue
        windows = request_windows(flow, first_day, last_day)
        run_first, run_last, outcome, failed_steps = newest
        stopped = outcome == "cancelled" or failed_steps or cancel_requested is not None
        if (run_first, run_last) == windows[-1] or stopped:
            connection.execute(FINISH, (request_id,))
        else:
            to_start.append((request_id, *windows[-1]))
    connection.commit()
    return to_start


def follow_runs(connection: psycopg.Connection, instance: DagsterInstance) -> SensorResult:
    schema_row = connection.execute("select current_schema()").fetchone()
    assert schema_row is not None
    schema = schema_row[0]
    running = instance.get_run_records(
        RunsFilter(tags={FLOW_TAG: [BOOTSTRAP, SYNC]}, statuses=UNFINISHED)
    )
    # A scheduled run carries no schema and writes where the instance's settings point.
    copy_steps(
        instance,
        connection,
        [
            record.dagster_run.run_id
            for record in running
            if record.dagster_run.tags.get(SCHEMA_TAG, schema) == schema
        ],
    )
    record_finished_runs(instance, connection, schema)
    return SensorResult(
        run_requests=[
            RunRequest(
                run_key=f"flow-request-{request_id}-older",
                job_name=history_bootstrap.name,
                tags={
                    RANGE_START: first.isoformat(),
                    RANGE_END: last.isoformat(),
                    SCHEMA_TAG: schema,
                    REQUEST_TAG: str(request_id),
                },
            )
            for request_id, first, last in follow_requests(connection)
        ]
    )


@sensor(
    jobs=[history_bootstrap],
    minimum_interval_seconds=MONITOR_INTERVAL_SECONDS,
    default_status=DefaultSensorStatus.RUNNING,
    description="Copies each run's progress, records each finished run and finishes its request.",
)
def flow_run_sensor(context: SensorEvaluationContext, database: Database) -> SensorResult:
    with database.connect() as connection:
        return follow_runs(connection, context.instance)
