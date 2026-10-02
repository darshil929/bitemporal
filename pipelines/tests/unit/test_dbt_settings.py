"""dbt runs without reporting its use to dbt Labs, in CI and on every installation."""

from pathlib import Path

from dbt.config.project import read_project_flags

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"


def test_dbt_sends_no_usage_reports() -> None:
    flags = read_project_flags(str(DBT_DIR), str(DBT_DIR))

    assert flags.send_anonymous_usage_stats is False
