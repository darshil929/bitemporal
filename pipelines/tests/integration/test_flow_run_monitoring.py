"""Runs followed while they go and once they end: steps copied, requests finished, older years started."""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from dagster import (
    DagsterInstance,
    MaterializeResult,
    SensorResult,
    asset,
    build_sensor_context,
    materialize,
)
from psycopg.types.json import Jsonb

from fixtures.database import MIGRATION_SCHEMA, PointedDatabase
from pipelines.flow_run_monitoring import copy_steps, flow_run_sensor, follow_runs
from pipelines.flows import REQUEST_TAG, SCHEMA_TAG
from pipelines.jobs import FLOW_TAG, RANGE_END, RANGE_START, SYNC

STARTED = (
    "insert into flow_request (flow, first_day, last_day, requested_by, status, started_at)"
    " select %s, %s, %s, id, 'started', now() from app_user returning id"
)
RECORDED = (
    "insert into flow_run (run_id, flow, first_day, last_day, started_at, ended_at, outcome,"
    " checks_passed, failed_steps, request_id) values (%(run)s, %(flow)s, %(first)s, %(last)s,"
    " now(), now(), %(outcome)s, 0, %(steps)s, %(request)s)"
)
RECENT_YEARS = ("2024-11-11", "2026-11-10")
OLDER_YEARS = ("2011-06-22", "2024-11-10")


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


def started(connection: psycopg.Connection, flow: str, first: str, last: str) -> int:
    row = connection.execute(STARTED, (flow, first, last)).fetchone()
    connection.commit()
    assert row is not None
    return int(row[0])


def recorded(
    connection: psycopg.Connection, request: int, days: tuple[str, str], **changed: Any
) -> None:
    values = {
        "run": f"run-{days[0]}",
        "flow": "bootstrap",
        "first": days[0],
        "last": days[1],
        "outcome": "succeeded",
        "steps": Jsonb([]),
        "request": request,
    }
    connection.execute(RECORDED, values | changed)
    connection.commit()


def status_of(connection: psycopg.Connection, request: int) -> str:
    row = connection.execute("select status from flow_request where id = %s", (request,)).fetchone()
    assert row is not None
    return str(row[0])


def test_a_request_finishes_once_its_run_is_recorded(
    connection: psycopg.Connection, instance: DagsterInstance
) -> None:
    request = started(connection, SYNC, "2026-11-04", "2026-11-10")
    follow_runs(connection, instance)
    still_going = status_of(connection, request)
    recorded(connection, request, ("2026-11-04", "2026-11-10"), flow=SYNC)

    result = follow_runs(connection, instance)

    assert still_going == "started"
    assert status_of(connection, request) == "finished"
    assert result.run_requests == []


@pytest.mark.parametrize(
    ("changed", "continues"),
    [
        ({}, True),
        ({"outcome": "failed"}, True),
        ({"outcome": "failed", "steps": Jsonb(["dbt_models"])}, False),
        ({"outcome": "cancelled"}, False),
    ],
)
def test_a_bootstrap_takes_its_older_years_unless_a_step_failed_or_it_was_cancelled(
    connection: psycopg.Connection,
    instance: DagsterInstance,
    changed: dict[str, Any],
    continues: bool,
) -> None:
    """Failed days alone leave the models built, so the older years still load."""
    request = started(connection, "bootstrap", OLDER_YEARS[0], RECENT_YEARS[1])
    recorded(connection, request, RECENT_YEARS, **changed)

    result = follow_runs(connection, instance)

    assert status_of(connection, request) == ("started" if continues else "finished")
    assert [(run.run_key, run.job_name, run.tags) for run in result.run_requests or []] == (
        [
            (
                f"flow-request-{request}-older",
                "history_bootstrap",
                {
                    RANGE_START: OLDER_YEARS[0],
                    RANGE_END: OLDER_YEARS[1],
                    SCHEMA_TAG: MIGRATION_SCHEMA,
                    REQUEST_TAG: str(request),
                },
            )
        ]
        if continues
        else []
    )


def test_a_bootstrap_finishes_once_its_older_years_are_recorded(
    connection: psycopg.Connection, instance: DagsterInstance
) -> None:
    request = started(connection, "bootstrap", OLDER_YEARS[0], RECENT_YEARS[1])
    recorded(connection, request, RECENT_YEARS)
    recorded(connection, request, OLDER_YEARS)

    follow_runs(connection, instance)

    assert status_of(connection, request) == "finished"


def test_a_run_s_finished_steps_are_copied_once(
    connection: psycopg.Connection, instance: DagsterInstance
) -> None:
    @asset(name="bse_bhavcopy")
    def prices() -> MaterializeResult:
        return MaterializeResult(metadata={"published": 1})

    run_id = materialize([prices], instance=instance).run_id

    copy_steps(instance, connection, [run_id])
    copy_steps(instance, connection, [run_id])

    assert connection.execute("select run_id, step, outcome from flow_run_step").fetchall() == [
        (run_id, "bse_bhavcopy", "succeeded")
    ]


def test_the_sensor_records_a_finished_run_of_its_schema(
    migrated: Config, postgres_dsn: str, instance: DagsterInstance
) -> None:
    @asset(name="bse_bhavcopy")
    def prices() -> MaterializeResult:
        return MaterializeResult(metadata={"published": 1})

    tags = {FLOW_TAG: SYNC, RANGE_START: "2026-11-04", RANGE_END: "2026-11-10"}
    run_id = materialize(
        [prices], instance=instance, tags=tags | {SCHEMA_TAG: MIGRATION_SCHEMA}
    ).run_id
    context = build_sensor_context(
        instance=instance, resources={"database": PointedDatabase(dsn=postgres_dsn)}
    )

    assert isinstance(flow_run_sensor(context), SensorResult)
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as check:
        assert check.execute("select run_id from flow_run").fetchall() == [(run_id,)]
