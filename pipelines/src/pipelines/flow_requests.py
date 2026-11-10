"""The application's requests for a run of a flow, refused for the launcher's reasons or started.

A request waits in Postgres until the daemon evaluates the sensor, so nothing reaches Dagster over
the network. The oldest request is taken first and one at a time, since a flow runs alone.
"""

from datetime import date, timedelta

import psycopg
from dagster import (
    DagsterInstance,
    DefaultSensorStatus,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    sensor,
)
from psycopg.types.json import Jsonb

from pipelines.flows import RECENT, REQUEST_TAG, SCHEMA_TAG, FlowRefused, refuse_unless_ready
from pipelines.jobs import BOOTSTRAP, RANGE_END, RANGE_START, SYNC, daily_sync, history_bootstrap
from pipelines.resources import Database

REQUEST_INTERVAL_SECONDS = 30

JOBS = {BOOTSTRAP: history_bootstrap.name, SYNC: daily_sync.name}

# A request another evaluation holds is passed over rather than waited for.
OLDEST_REQUEST = """
select id, flow, first_day, last_day from flow_request
where status = 'requested'
order by requested_at, id
limit 1
for update skip locked
"""
REFUSE = "update flow_request set status = 'refused', refusal = %s where id = %s"
START = "update flow_request set status = 'started', started_at = now() where id = %s"


def request_windows(flow: str, first: date, last: date) -> list[tuple[date, date]]:
    """The runs a request takes: a sync's range in one; a bootstrap's two most recent years, then
    the days before them."""
    if flow == SYNC:
        return [(first, last)]
    split = last - RECENT
    if split < first:
        return [(first, last)]
    return [(split + timedelta(days=1), last), (first, split)]


def take_request(
    connection: psycopg.Connection, instance: DagsterInstance
) -> RunRequest | SkipReason:
    """The run for the oldest request waiting, or why there is none; the request moves on."""
    request = connection.execute(OLDEST_REQUEST).fetchone()
    if request is None:
        return SkipReason("no flow request waiting")
    request_id, flow, first_day, last_day = request
    schema = connection.execute("select current_schema()").fetchone()
    assert schema is not None
    try:
        refuse_unless_ready(connection, instance, schema[0])
    except FlowRefused as refused:
        why = Jsonb({"reason": refused.reason, **refused.facts})
        connection.execute(REFUSE, (why, request_id))
        connection.commit()
        return SkipReason(f"flow request {request_id} refused: {refused}")

    first, last = request_windows(flow, first_day, last_day)[0]
    connection.execute(START, (request_id,))
    connection.commit()
    return RunRequest(
        run_key=f"flow-request-{request_id}",
        job_name=JOBS[flow],
        tags={
            RANGE_START: first.isoformat(),
            RANGE_END: last.isoformat(),
            SCHEMA_TAG: schema[0],
            REQUEST_TAG: str(request_id),
        },
    )


@sensor(
    jobs=[daily_sync, history_bootstrap],
    minimum_interval_seconds=REQUEST_INTERVAL_SECONDS,
    default_status=DefaultSensorStatus.RUNNING,
    description="Starts the run an admin requested in the application, or records why it cannot.",
)
def flow_request_sensor(
    context: SensorEvaluationContext, database: Database
) -> RunRequest | SkipReason:
    with database.connect() as connection:
        return take_request(connection, context.instance)
