"""The Dagster entry point loads, carrying the assets and the resources they ask for."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import AssetKey, AssetSelection, Definitions, define_asset_job
from dagster._core.execution.api import create_execution_plan

from pipelines.assets.ingestion.calendar import INGESTION_DAYS
from pipelines.assets.transform.dbt import SOURCE_WRITERS
from pipelines.definitions import defs

INGESTION = ("bse_bhavcopy", "nse_bhavcopy", "bse_delivery", "nse_delivery")


def test_definitions_loads() -> None:
    assert isinstance(defs, Definitions)


def test_both_venues_are_ingested_by_trading_day() -> None:
    keys = {key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()}

    assert {"bse_bhavcopy", "nse_bhavcopy"} <= keys


def test_each_dbt_model_is_its_own_asset() -> None:
    """A failed dbt test then blocks what reads that model rather than the whole run."""
    keys = {key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()}

    assert {"stg_price_daily", "stg_listings", "int_venue_spread"} <= keys


def test_the_models_wait_for_the_assets_that_fill_their_sources() -> None:
    graph = defs.resolve_asset_graph()
    upstream = graph.get(AssetKey("stg_price_daily")).parent_keys

    assert AssetKey(["market", "price_daily"]) in upstream
    assert {AssetKey("bse_bhavcopy"), AssetKey("nse_bhavcopy")} <= graph.get(
        AssetKey(["market", "price_daily"])
    ).parent_keys


def test_the_models_wait_for_both_venues_corporate_actions() -> None:
    writers = defs.resolve_asset_graph().get(AssetKey(["market", "corporate_action"])).parent_keys

    assert {AssetKey("corporate_actions"), AssetKey("nse_corporate_actions")} <= writers


def test_every_ingestion_asset_shares_one_calendar_of_days() -> None:
    """Dagster runs assets in one job only where they share a partitions definition."""
    calendars = [defs.resolve_assets_def(name).partitions_def for name in INGESTION]

    assert calendars == [INGESTION_DAYS] * len(INGESTION)


def test_one_job_runs_every_asset_at_both_venues() -> None:
    job = define_asset_job("every_asset", selection=AssetSelection.all())

    resolved = job.resolve(asset_graph=defs.resolve_asset_graph())

    assert resolved.partitions_def == INGESTION_DAYS


def test_the_calendar_runs_from_the_first_priced_day_to_today_in_india() -> None:
    """Half past midnight in India is still the day before in UTC.

    NSE's prices are registered from 22 June 2011, and both venues publish a day's files the same
    evening, so today is a partition.
    """
    just_past_midnight = datetime(2026, 9, 27, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))

    days = INGESTION_DAYS.get_partition_keys(current_time=just_past_midnight)

    assert days[0] == "2011-06-22"
    assert days[-1] == "2026-09-27"


def test_every_asset_finds_the_resources_it_asks_for() -> None:
    """A missing resource fails here rather than on the first partition of a backfill."""
    Definitions.validate_loadable(defs)


def test_a_run_builds_the_models_after_every_table_they_read() -> None:
    """A table held only as a source is left out of a job, which then starts the models first."""
    job = define_asset_job("every_asset", selection=AssetSelection.all())

    plan = create_execution_plan(job.resolve(asset_graph=defs.resolve_asset_graph()))

    waits_for = plan.get_step_by_key("dbt_models").get_execution_dependency_keys()
    assert waits_for == {f"market__{table}" for table in SOURCE_WRITERS}
