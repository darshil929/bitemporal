"""Both flows run every asset over recorded days into an empty database, the models included.

The venues answer from responses recorded for 14 August 2026 at both, BSE's delivery trimmed to the
instruments its price file carries, and every other day of the week as unpublished. Corporate actions answer for the years recorded and refuse the rest, as BSE's
host refuses this machine.
"""

from datetime import date
from pathlib import Path

import pytest
from dagster import DagsterInstance, Definitions, ExecuteInProcessResult
from dagster_dbt import DbtCliResource
from test_corporate_action_asset import RecordedActions
from test_delivery_asset import RecordedDeliveries
from test_ingestion_assets import RecordedBhavcopies, payload, rows
from test_instrument_name_asset import RecordedNseLists, RecordedScripLists
from test_nse_corporate_action_asset import RecordedActions as RecordedNseActions

from conftest import MIGRATION_SCHEMA, PointedDatabase, dbt_environment
from pipelines.assets.transform.dbt import dbt_project
from pipelines.definitions import defs
from pipelines.jobs import FLOW_TAG, RANGE_END, RANGE_START, daily_sync, history_bootstrap

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
DAY = date(2026, 8, 14)
WEEK = {RANGE_START: "2026-08-08", RANGE_END: "2026-08-14"}


def recorded(dsn: str) -> Definitions:
    return Definitions(
        assets=defs.assets,
        asset_checks=defs.asset_checks,
        jobs=[history_bootstrap, daily_sync],
        resources={
            "database": PointedDatabase(dsn=dsn),
            "bhavcopies": RecordedBhavcopies(
                {
                    "BSE": {DAY: payload("bse_bhavcopy_equity", "20260814.csv")},
                    "NSE": {DAY: payload("nse_bhavcopy_equity", "20260814.csv.zip")},
                }
            ),
            "deliveries": RecordedDeliveries(
                {
                    "BSE": {DAY: (CASSETTES / "bse_delivery" / "20260814_priced.zip").read_bytes()},
                    "NSE": {DAY: (CASSETTES / "nse_delivery" / "20260814.csv").read_bytes()},
                }
            ),
            "actions": RecordedActions(),
            "nse_actions": RecordedNseActions(),
            "scrip_lists": RecordedScripLists(),
            "nse_lists": RecordedNseLists(),
            "dbt": DbtCliResource(project_dir=dbt_project),
        },
    )


def run(definitions: Definitions, job: str, instance: DagsterInstance) -> ExecuteInProcessResult:
    return definitions.resolve_job_def(job).execute_in_process(instance=instance, tags=WEEK)


def venue_counts(dsn: str, table: str) -> list[tuple]:
    return rows(dsn, f"select venue, count(*) from {table} group by venue order by venue")


def test_a_bootstrap_then_a_sync_over_the_same_week_load_it_once(
    dbt_built: None, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in dbt_environment(postgres_dsn).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATA_ENV", MIGRATION_SCHEMA)
    definitions = recorded(postgres_dsn)

    with DagsterInstance.ephemeral() as instance:
        bootstrap = run(definitions, "history_bootstrap", instance)
        bars = venue_counts(postgres_dsn, "price_daily")
        sync = run(definitions, "daily_sync", instance)

    assert bootstrap.success, bootstrap.get_failed_step_keys()
    assert sync.success, sync.get_failed_step_keys()
    assert bootstrap.dagster_run.tags[FLOW_TAG] == "bootstrap"
    assert sync.dagster_run.tags[FLOW_TAG] == "sync"
    assert [venue for venue, _ in bars] == ["BSE", "NSE"]
    assert venue_counts(postgres_dsn, "price_daily") == bars
    delivered = dict(venue_counts(postgres_dsn, "delivery_daily"))
    assert delivered["BSE"] == dict(bars)["BSE"]
    assert 0 < delivered["NSE"] <= dict(bars)["NSE"]
    assert rows(postgres_dsn, "select venue from trading_day order by venue") == [
        ("BSE",),
        ("NSE",),
    ]
    assert rows(postgres_dsn, "select count(*) from stg_price_daily") == [
        (sum(count for _, count in bars),)
    ]
    written = sync.asset_materializations_for_node("bse_bhavcopy")[0].metadata["written"]
    assert written.value == 0
