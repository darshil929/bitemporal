"""A request from the application is started as a run of its flow, or refused with the reason."""

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest
from alembic.config import Config
from dagster import (
    DagsterInstance,
    DagsterRunStatus,
    RunRequest,
    SkipReason,
    build_sensor_context,
)
from dagster._core.test_utils import create_run_for_test

from fixtures.database import MIGRATION_SCHEMA, PointedDatabase
from pipelines.flow_requests import flow_request_sensor, request_windows, take_request
from pipelines.flows import REQUEST_TAG, SCHEMA_TAG
from pipelines.jobs import FLOW_TAG, RANGE_END, RANGE_START, SYNC

REQUEST = (
    "insert into flow_request (flow, first_day, last_day, requested_by)"
    " select %s, %s, %s, id from app_user returning id"
)
REQUESTS = "select status, started_at is not null, refusal from flow_request order by id"


@pytest.fixture
def connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        connection.execute(
            "insert into app_user (username, display_name, role, password_hash)"
            " values ('admin', 'Admin', 'admin', 'unused')"
        )
        connection.commit()
        yield connection


@pytest.fixture
def instance() -> Iterator[DagsterInstance]:
    with DagsterInstance.ephemeral() as instance:
        yield instance


def requested(
    connection: psycopg.Connection,
    flow: str = SYNC,
    first: str = "2026-11-04",
    last: str = "2026-11-10",
) -> int:
    row = connection.execute(REQUEST, (flow, first, last)).fetchone()
    connection.commit()
    assert row is not None
    return int(row[0])


def test_a_waiting_request_is_started_as_a_run_of_its_days(
    connection: psycopg.Connection, instance: DagsterInstance
) -> None:
    request = requested(connection)

    run = take_request(connection, instance)

    assert isinstance(run, RunRequest)
    assert (run.run_key, run.job_name) == (f"flow-request-{request}", "daily_sync")
    assert run.tags == {
        RANGE_START: "2026-11-04",
        RANGE_END: "2026-11-10",
        SCHEMA_TAG: MIGRATION_SCHEMA,
        REQUEST_TAG: str(request),
    }
    assert connection.execute(REQUESTS).fetchall() == [("started", True, None)]


def test_a_bootstrap_starts_with_its_two_most_recent_years(
    connection: psycopg.Connection, instance: DagsterInstance
) -> None:
    requested(connection, "bootstrap", "2011-06-22", "2026-11-10")

    run = take_request(connection, instance)

    assert isinstance(run, RunRequest)
    assert run.job_name == "history_bootstrap"
    assert (run.tags[RANGE_START], run.tags[RANGE_END]) == ("2024-11-11", "2026-11-10")


def test_a_bootstrap_takes_its_older_years_in_a_second_run() -> None:
    assert request_windows("bootstrap", date(2011, 6, 22), date(2026, 11, 10)) == [
        (date(2024, 11, 11), date(2026, 11, 10)),
        (date(2011, 6, 22), date(2024, 11, 10)),
    ]
    assert request_windows("bootstrap", date(2025, 6, 1), date(2026, 11, 10)) == [
        (date(2025, 6, 1), date(2026, 11, 10))
    ]


def test_a_request_while_a_flow_runs_is_refused_with_that_flow_s_days(
    connection: psycopg.Connection, instance: DagsterInstance
) -> None:
    create_run_for_test(
        instance,
        job_name="daily_sync",
        status=DagsterRunStatus.STARTED,
        tags={FLOW_TAG: SYNC, RANGE_START: "2026-11-03", RANGE_END: "2026-11-09"},
    )
    requested(connection)

    skipped = take_request(connection, instance)

    ((status, started, refusal),) = connection.execute(REQUESTS).fetchall()
    assert isinstance(skipped, SkipReason)
    assert (status, started) == ("refused", False)
    assert (refusal["reason"], refusal["first_day"], refusal["last_day"]) == (
        "flow_running",
        "2026-11-03",
        "2026-11-09",
    )


def test_the_oldest_request_is_taken_first_and_alone(
    connection: psycopg.Connection, instance: DagsterInstance
) -> None:
    first = requested(connection)
    requested(connection, first="2026-11-05")

    run = take_request(connection, instance)

    assert isinstance(run, RunRequest) and run.tags[REQUEST_TAG] == str(first)
    assert [row[0] for row in connection.execute(REQUESTS)] == ["started", "requested"]


def test_the_sensor_waits_while_no_request_does(
    migrated: Config, postgres_dsn: str, instance: DagsterInstance
) -> None:
    context = build_sensor_context(
        instance=instance, resources={"database": PointedDatabase(dsn=postgres_dsn)}
    )

    assert isinstance(flow_request_sensor(context), SkipReason)
