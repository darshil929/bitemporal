"""What the flow launcher shows in the terminal, and where a run's own output goes."""

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from pipelines import flows
from pipelines.flows import FlowReport, output_to

STEP_LINE = "STEP_SUCCESS - Finished execution of step"
DBT_LINE = "Done. PASS=155 WARN=0 ERROR=0"


def a_step_process(text: str) -> None:
    """A run's steps execute in processes of their own, which inherit the launcher's descriptors."""
    subprocess.run(
        [sys.executable, "-c", f"import sys; print({text!r}); print({text!r}, file=sys.stderr)"],
        check=True,
    )


def test_a_runs_output_is_kept_in_its_file(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "logs" / "sync.log"

    with output_to(log):
        print("from the launcher")
        a_step_process(STEP_LINE)
    print("after the run")

    shown = capfd.readouterr()
    kept = log.read_text()
    assert shown.out == "after the run\n"
    assert shown.err == ""
    assert "from the launcher" in kept
    assert kept.count(STEP_LINE) == 2


def test_the_terminal_returns_when_a_run_raises(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(RuntimeError), output_to(tmp_path / "sync.log"):
        raise RuntimeError("step failed")
    print("after the run")

    assert capfd.readouterr().out == "after the run\n"


class Settings:
    database_url = "postgresql+psycopg://smoke@localhost:5434/smoke"
    schema_name = "dev"
    data_env = "dev"


class Database:
    @contextmanager
    def connect(self) -> Iterator[None]:
        yield None


def run_window(*_: object) -> FlowReport:
    print(DBT_LINE)
    a_step_process(STEP_LINE)
    return FlowReport(date(2026, 9, 25), date(2026, 9, 25), {}, [], 108, [], [], [], [])


@pytest.fixture
def launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The launcher with its database, instance and run stood in for; returns the instance home."""

    class Instance:
        root_directory = str(tmp_path)

        @staticmethod
        def get() -> "Instance":
            return Instance()

    monkeypatch.setattr(flows, "DatabaseSettings", Settings)
    monkeypatch.setattr(flows, "Database", Database)
    monkeypatch.setattr(flows, "DagsterInstance", Instance)
    monkeypatch.setattr(flows, "refuse_unless_ready", lambda *_: None)
    monkeypatch.setattr(flows, "run_window", run_window)
    return tmp_path


def test_the_terminal_shows_the_target_the_log_and_the_report(
    launcher: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    exit_code = flows.main(["sync", "--from", "2026-09-25", "--to", "2026-09-25"])

    shown = capfd.readouterr()
    (log,) = (launcher / flows.LOG_FOLDER).glob("sync-*.log")
    assert exit_code == 0
    assert shown.out.splitlines()[:3] == [
        f"database smoke on localhost:5434, schema dev, Dagster instance {launcher}",
        f"run output in {log}",
        "2026-09-25 to 2026-09-25",
    ]
    assert "  checks 108 passed, 0 warned, 0 failed" in shown.out
    assert STEP_LINE not in shown.out + shown.err
    assert DBT_LINE not in shown.out
    assert DBT_LINE in log.read_text()
    assert log.read_text().count(STEP_LINE) == 2


def test_verbose_shows_each_runs_output(launcher: Path, capfd: pytest.CaptureFixture[str]) -> None:
    flows.main(["sync", "--from", "2026-09-25", "--to", "2026-09-25", "--verbose"])

    shown = capfd.readouterr()
    assert DBT_LINE in shown.out
    assert STEP_LINE in shown.out
    assert "run output in" not in shown.out
    assert not (launcher / flows.LOG_FOLDER).exists()
