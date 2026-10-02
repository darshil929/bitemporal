"""The dbt models are loaded from a manifest parsed after the project's latest change."""

import os
import time
from pathlib import Path

import pytest
from dagster_dbt import DbtProject
from dagster_dbt.dbt_project import DagsterDbtProjectPreparer

from pipelines.assets.transform.dbt import prepare

PARSED_AT = time.time() - 100
WRITTEN_BEFORE = PARSED_AT - 100


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """The projects parsed, in place of running dbt."""
    parsed: list[Path] = []

    def record(self: DagsterDbtProjectPreparer, project: DbtProject) -> None:
        parsed.append(project.project_dir)

    monkeypatch.setattr(DagsterDbtProjectPreparer, "prepare", record)
    return parsed


def write(path: Path, at: float, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (at, at))
    os.utime(path.parent, (at, at))


def project_parsed(tmp_path: Path) -> DbtProject:
    """A project of two models whose manifest was parsed after both were written."""
    write(tmp_path / "dbt_project.yml", WRITTEN_BEFORE, "name: example\n")
    write(tmp_path / "models" / "staging" / "stg_bars.sql", WRITTEN_BEFORE, "select 1\n")
    write(tmp_path / "models" / "staging" / "stg_names.sql", WRITTEN_BEFORE, "select 2\n")
    os.utime(tmp_path / "models", (WRITTEN_BEFORE, WRITTEN_BEFORE))
    write(tmp_path / "target" / "manifest.json", PARSED_AT, "{}\n")
    return DbtProject(project_dir=tmp_path, profiles_dir=tmp_path)


def test_an_absent_manifest_is_parsed(tmp_path: Path, parses: list[Path]) -> None:
    write(tmp_path / "dbt_project.yml", WRITTEN_BEFORE, "name: example\n")
    project = DbtProject(project_dir=tmp_path, profiles_dir=tmp_path)

    prepare(project)

    assert parses == [tmp_path]


def test_a_manifest_older_than_a_model_is_parsed_again(tmp_path: Path, parses: list[Path]) -> None:
    project = project_parsed(tmp_path)
    write(tmp_path / "models" / "intermediate" / "int_names.sql", time.time(), "select 3\n")

    prepare(project)

    assert parses == [tmp_path]


def test_a_manifest_naming_a_removed_model_is_parsed_again(
    tmp_path: Path, parses: list[Path]
) -> None:
    project = project_parsed(tmp_path)
    (tmp_path / "models" / "staging" / "stg_names.sql").unlink()

    prepare(project)

    assert parses == [tmp_path]


def test_a_current_manifest_is_loaded_as_it_stands(tmp_path: Path, parses: list[Path]) -> None:
    """A run's own output, dbt's log and its user file are written after the parse."""
    project = project_parsed(tmp_path)
    write(tmp_path / "target" / "dbt_models-run" / "manifest.json", time.time(), "{}\n")
    write(tmp_path / "logs" / "dbt.log", time.time())
    write(tmp_path / ".user.yml", time.time(), "id: example\n")

    prepare(project)

    assert parses == []
