"""A finished flow run is recorded in the database it wrote to, with the report its events give."""

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest
from alembic.config import Config
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    DagsterInstance,
    DagsterRunStatus,
    MaterializeResult,
    asset,
    asset_check,
    materialize,
)
from dagster._core.test_utils import create_run_for_test

from fixtures.database import MIGRATION_SCHEMA
from pipelines import flows
from pipelines.flows import REQUEST_TAG, ROWS_FOUND, SCHEMA_TAG, record_finished_runs
from pipelines.jobs import FLOW_TAG, RANGE_END, RANGE_START, SYNC

OPTIONS = f"-csearch_path={MIGRATION_SCHEMA},public"
RUN_TAGS = {FLOW_TAG: SYNC, RANGE_START: "2026-11-03", RANGE_END: "2026-11-09"}
PRICES = {"published": 5, "unpublished": 2, "failed": 0}
ONE_SIDED = "assert_capital_actions_reported_by_both_venues"
KEY = "20260101-20261231"
SHORT_ANSWER = f"answer for {KEY} lacks 96 actions already stored"
FAILED_FETCH = (
    "insert into ingestion_log (source_id, partition_key, schema_version, outcome, detail)"
    f" values ('bse_corporate_actions', '{KEY}', 'v1', 'failed', %s)"
)
RUNS = (
    "select flow, first_day, last_day, outcome, counts, failures, warned_checks, failed_steps,"
    " unmaterialized from flow_run"
)


@pytest.fixture
def connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(postgres_dsn, options=OPTIONS) as connection:
        yield connection


@pytest.fixture
def instance() -> Iterator[DagsterInstance]:
    with DagsterInstance.ephemeral() as instance:
        yield instance


def a_sync(
    instance: DagsterInstance,
    dsn: str,
    schema: str | None = MIGRATION_SCHEMA,
    identity_fails: bool = False,
    fetch_fails: bool = False,
) -> str:
    """A sync's run id: prices with their counts and a check warned, then identity, then models."""

    @asset(name="bse_bhavcopy")
    def prices() -> MaterializeResult:
        if fetch_fails:
            with psycopg.connect(dsn, options=OPTIONS, autocommit=True) as fetches:
                fetches.execute(FAILED_FETCH, (SHORT_ANSWER,))
        return MaterializeResult(metadata=PRICES)

    @asset_check(asset=prices, name=ONE_SIDED)
    def one_sided() -> AssetCheckResult:
        return AssetCheckResult(
            passed=False, severity=AssetCheckSeverity.WARN, metadata={ROWS_FOUND: 16}
        )

    @asset(name="instrument_identity", deps=[prices])
    def identity() -> None:
        if identity_fails:
            raise RuntimeError("identity failed")

    @asset(name="dbt_models", deps=[identity])
    def models() -> None:
        return None

    tags = RUN_TAGS if schema is None else RUN_TAGS | {SCHEMA_TAG: schema}
    result = materialize(
        [prices, one_sided, identity, models], instance=instance, tags=tags, raise_on_error=False
    )
    return result.run_id


def test_a_finished_run_is_recorded_once_with_its_steps(
    instance: DagsterInstance, connection: psycopg.Connection, postgres_dsn: str
) -> None:
    run_id = a_sync(instance, postgres_dsn, identity_fails=True)

    assert record_finished_runs(instance, connection, MIGRATION_SCHEMA) == [run_id]
    assert record_finished_runs(instance, connection, MIGRATION_SCHEMA) == []
    assert connection.execute(RUNS).fetchall() == [
        (
            "sync",
            date(2026, 11, 3),
            date(2026, 11, 9),
            "failed",
            {"bse_bhavcopy": PRICES},
            [],
            [{"name": ONE_SIDED, "rows": 16}],
            ["instrument_identity"],
            ["dbt_models", "instrument_identity"],
        )
    ]
    assert connection.execute(
        "select step, outcome, started_at <= ended_at from flow_run_step order by step"
    ).fetchall() == [
        ("bse_bhavcopy", "succeeded", True),
        (f"bse_bhavcopy_{ONE_SIDED}", "succeeded", True),
        ("instrument_identity", "failed", True),
    ]


@pytest.mark.parametrize(
    ("fetch_fails", "outcome", "failures"),
    [
        (False, "succeeded", []),
        (True, "failed", [{"source": "bse_corporate_actions", "key": KEY, "detail": SHORT_ANSWER}]),
    ],
)
def test_a_failed_fetch_fails_a_run_dagster_counts_a_success(
    instance: DagsterInstance,
    connection: psycopg.Connection,
    postgres_dsn: str,
    fetch_fails: bool,
    outcome: str,
    failures: list[dict[str, str]],
) -> None:
    """A check of warning severity fails nothing; a failed day, range or list fails the run."""
    run_id = a_sync(instance, postgres_dsn, fetch_fails=fetch_fails)
    record = instance.get_run_record_by_id(run_id)
    assert record is not None and record.dagster_run.status == DagsterRunStatus.SUCCESS

    record_finished_runs(instance, connection, MIGRATION_SCHEMA)

    assert connection.execute("select outcome, failures from flow_run").fetchall() == [
        (outcome, failures)
    ]


def test_a_run_is_recorded_in_the_database_it_wrote_to(
    instance: DagsterInstance, connection: psycopg.Connection, postgres_dsn: str
) -> None:
    """A run from before runs carried their schema wrote here if this database logged a fetch."""
    a_sync(instance, postgres_dsn, schema="full")
    a_sync(instance, postgres_dsn, schema=None)
    fetched = a_sync(instance, postgres_dsn, schema=None, fetch_fails=True)

    assert record_finished_runs(instance, connection, MIGRATION_SCHEMA) == [fetched]


@pytest.mark.parametrize(
    ("status", "outcomes"),
    [(DagsterRunStatus.CANCELED, [("cancelled",)]), (DagsterRunStatus.STARTED, [])],
)
def test_a_cancelled_run_is_recorded_and_a_run_still_going_is_not(
    instance: DagsterInstance,
    connection: psycopg.Connection,
    status: DagsterRunStatus,
    outcomes: list[tuple[str]],
) -> None:
    create_run_for_test(
        instance,
        job_name="daily_sync",
        status=status,
        tags=RUN_TAGS | {SCHEMA_TAG: MIGRATION_SCHEMA},
    )

    record_finished_runs(instance, connection, MIGRATION_SCHEMA)

    assert connection.execute("select outcome from flow_run").fetchall() == outcomes


def test_a_run_names_the_request_it_was_started_for(
    instance: DagsterInstance, connection: psycopg.Connection
) -> None:
    connection.execute(
        "insert into app_user (username, display_name, role, password_hash)"
        " values ('admin', 'Admin', 'admin', 'unused')"
    )
    request = connection.execute(
        "insert into flow_request (flow, first_day, last_day, requested_by)"
        " select 'sync', '2026-11-03', '2026-11-09', id from app_user returning id"
    ).fetchone()
    assert request is not None
    create_run_for_test(
        instance,
        job_name="daily_sync",
        status=DagsterRunStatus.CANCELED,
        tags=RUN_TAGS | {SCHEMA_TAG: MIGRATION_SCHEMA, REQUEST_TAG: str(request[0])},
    )

    record_finished_runs(instance, connection, MIGRATION_SCHEMA)

    assert connection.execute("select request_id from flow_run").fetchall() == [(request[0],)]


def test_a_run_another_process_recorded_meanwhile_is_passed_over(
    instance: DagsterInstance,
    connection: psycopg.Connection,
    postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launcher and the daemon both record finished runs."""
    a_sync(instance, postgres_dsn)
    record_finished_runs(instance, connection, MIGRATION_SCHEMA)
    steps = connection.execute("select count(*) from flow_run_step").fetchone()
    monkeypatch.setattr(
        flows, "RECORDED", "select run_id from flow_run where false and run_id = any(%s)"
    )

    assert record_finished_runs(instance, connection, MIGRATION_SCHEMA) == []
    assert connection.execute("select count(*) from flow_run_step").fetchone() == steps
