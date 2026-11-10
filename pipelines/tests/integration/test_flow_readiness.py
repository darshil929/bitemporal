"""A flow starts only against a migrated database while no other flow and no dbt build runs."""

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dagster import DagsterInstance, DagsterRunStatus
from dagster._core.test_utils import create_run_for_test

from fixtures.database import MIGRATION_SCHEMA
from pipelines.flows import FlowRefused, refuse_unless_ready
from pipelines.jobs import FLOW_TAG, RANGE_END, RANGE_START, SYNC

TARGET = "dev"


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public")


def test_a_migrated_database_with_no_flow_running_is_ready(
    migrated: Config, postgres_dsn: str
) -> None:
    with DagsterInstance.ephemeral() as instance, connect(postgres_dsn) as connection:
        refuse_unless_ready(connection, instance, TARGET)


def test_a_database_behind_the_latest_migration_is_refused(
    migrated: Config, postgres_dsn: str
) -> None:
    command.downgrade(migrated, "-1")

    with (
        DagsterInstance.ephemeral() as instance,
        connect(postgres_dsn) as connection,
        pytest.raises(FlowRefused, match="make migrate") as refused,
    ):
        refuse_unless_ready(connection, instance, TARGET)

    assert refused.value.reason == "migration_behind"
    assert refused.value.facts["found"] < refused.value.facts["expected"]


def test_a_second_flow_is_refused_while_one_runs(migrated: Config, postgres_dsn: str) -> None:
    with DagsterInstance.ephemeral() as instance, connect(postgres_dsn) as connection:
        run = create_run_for_test(
            instance,
            job_name="daily_sync",
            status=DagsterRunStatus.STARTED,
            tags={FLOW_TAG: SYNC, RANGE_START: "2026-10-04", RANGE_END: "2026-10-10"},
        )

        with pytest.raises(FlowRefused, match="STARTED") as refused:
            refuse_unless_ready(connection, instance, TARGET)

    assert refused.value.reason == "flow_running"
    assert {
        key: refused.value.facts[key] for key in ("run_id", "flow", "first_day", "last_day")
    } == {
        "run_id": run.run_id,
        "flow": SYNC,
        "first_day": "2026-10-04",
        "last_day": "2026-10-10",
    }


def test_a_flow_is_refused_while_dbt_still_builds_its_target(
    migrated: Config, postgres_dsn: str
) -> None:
    """A build left running by a flow that ended still writes to the database."""
    with psycopg.connect(postgres_dsn, application_name="dbt") as build:
        build.execute(f'/* {{"app": "dbt", "target_name": "{TARGET}"}} */ select 1')

        with DagsterInstance.ephemeral() as instance, connect(postgres_dsn) as connection:
            with pytest.raises(FlowRefused, match=f"dbt is still building {TARGET}") as refused:
                refuse_unless_ready(connection, instance, TARGET)
            assert (refused.value.reason, refused.value.facts["target"]) == ("dbt_building", TARGET)
            connection.rollback()

            refuse_unless_ready(connection, instance, "full")
