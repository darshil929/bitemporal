"""The Dagster instance configuration and daemon agent committed for scheduled syncs."""

import plistlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from dagster import DagsterInstance, DagsterRunStatus
from dagster._core.storage.dagster_run import IN_PROGRESS_RUN_STATUSES, DagsterRun, RunsFilter
from dagster._core.test_utils import create_run_for_test
from dagster._utils.tags import TagConcurrencyLimitsCounter

from pipelines.jobs import FLOW_TAG, SYNC

REPOSITORY = Path(__file__).resolve().parents[3]
INSTANCE_CONFIG = REPOSITORY / "infra" / "dagster" / "dagster.yaml"
DAEMON_AGENT = REPOSITORY / "infra" / "launchd" / "com.bitemporal.dagster-daemon.plist"


@pytest.fixture
def instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[DagsterInstance]:
    """An instance home holding the committed configuration, as the switch-on steps copy it."""
    shutil.copy(INSTANCE_CONFIG, tmp_path / "dagster.yaml")
    monkeypatch.setenv("DAGSTER_HOME", str(tmp_path))
    configured = DagsterInstance.get()
    yield configured
    configured.dispose()


def test_one_flow_runs_at_a_time(instance: DagsterInstance) -> None:
    queue = instance.get_concurrency_config().run_queue_config

    assert queue is not None
    assert queue.tag_concurrency_limits == [{"key": FLOW_TAG, "limit": 1}]


def test_a_scheduled_sync_waits_for_a_flow_launched_from_the_command_line(
    instance: DagsterInstance,
) -> None:
    """The launcher runs a job in process, so its run never passes through the queue."""
    create_run_for_test(
        instance, job_name="daily_sync", status=DagsterRunStatus.STARTED, tags={FLOW_TAG: SYNC}
    )
    in_progress = [
        record.dagster_run
        for record in instance.get_run_records(RunsFilter(statuses=IN_PROGRESS_RUN_STATUSES))
    ]
    limits = instance.get_concurrency_config().run_queue_config
    assert limits is not None
    counter = TagConcurrencyLimitsCounter(limits.tag_concurrency_limits, in_progress)

    assert counter.is_blocked(DagsterRun(job_name="daily_sync", tags={FLOW_TAG: SYNC}))
    assert not counter.is_blocked(DagsterRun(job_name="another_job", tags={}))


def test_a_machine_asleep_through_several_scheduled_times_runs_one_sync(
    instance: DagsterInstance,
) -> None:
    """A sync covers the seven days ending on its day."""
    assert instance.scheduler is not None
    assert instance.scheduler.max_catchup_runs == 1


def test_usage_statistics_are_not_sent(instance: DagsterInstance) -> None:
    assert not instance.telemetry_enabled


def test_the_daemon_agent_runs_the_definitions_from_the_repository() -> None:
    agent = plistlib.loads(DAEMON_AGENT.read_bytes())

    assert agent["ProgramArguments"] == [
        "__UV__",
        "run",
        "--env-file",
        ".env",
        "dagster-daemon",
        "run",
        "-m",
        "pipelines.definitions",
    ]
    assert agent["WorkingDirectory"] == "__REPOSITORY__"
    assert agent["RunAtLoad"] and agent["KeepAlive"]
