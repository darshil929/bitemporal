"""The dbt models are built one at a time, then tested in parallel."""

from collections.abc import Iterator
from typing import Any

import pytest
from dagster import materialize
from dagster_dbt import DbtCliResource

from pipelines.assets.transform.dbt import dbt_models, dbt_project
from pipelines.config.settings import DatabaseSettings


class Invocation:
    """A dbt command that ran and reported nothing."""

    def stream(self) -> Iterator[Any]:
        return iter(())


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
