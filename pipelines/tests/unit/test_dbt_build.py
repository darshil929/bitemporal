"""The dbt models are built one at a time, then tested in parallel, and dbt ends with its step."""

import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from dagster import materialize
from dagster_dbt import DbtCliResource

from pipelines.assets.transform.dbt import dbt_models, dbt_project
from pipelines.config.settings import DatabaseSettings


class Invocation:
    """A dbt command that ran and reported nothing."""

    def __init__(self) -> None:
        self.process = subprocess.Popen([sys.executable, "-c", ""])
        self.process.wait()

    def stream(self) -> Iterator[Any]:
        return iter(())


class Unreadable:
    """A dbt command still running when its output can no longer be read."""

    def __init__(self) -> None:
        self.process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])

    def stream(self) -> Iterator[Any]:
        yield from ()
        raise KeyError("model.bitemporal.a_model_the_manifest_does_not_list")


def test_views_are_replaced_one_at_a_time_before_the_tests_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two views replaced at once deadlock on the views built on both."""
    commands: list[list[str]] = []

    def record(self: DbtCliResource, args: list[str], **_: object) -> Invocation:
        commands.append(list(args))
        return Invocation()

    monkeypatch.setattr(DbtCliResource, "cli", record)

    result = materialize([dbt_models], resources={"dbt": DbtCliResource(project_dir=dbt_project)})

    target = DatabaseSettings().data_env
    assert result.success
    assert commands == [
        ["seed", "--target", target, "--threads", "1"],
        ["run", "--target", target, "--threads", "1"],
        ["test", "--target", target],
    ]


def test_a_dbt_command_ends_with_the_step_that_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A step that fails while dbt runs leaves no dbt writing to the database."""
    started: list[Unreadable] = []

    def start(self: DbtCliResource, args: list[str], **_: object) -> Unreadable:
        started.append(Unreadable())
        return started[-1]

    monkeypatch.setattr(DbtCliResource, "cli", start)

    try:
        result = materialize(
            [dbt_models],
            resources={"dbt": DbtCliResource(project_dir=dbt_project)},
            raise_on_error=False,
        )

        assert not result.success
        assert [command.process.poll() is not None for command in started] == [True]
    finally:
        for command in started:
            command.process.kill()
            command.process.wait()
