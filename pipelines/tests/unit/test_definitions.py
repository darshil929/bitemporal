"""The Dagster entry point loads, carrying the assets and the resources they ask for."""

from dagster import AssetKey, Definitions

from pipelines.definitions import defs


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


def test_every_asset_finds_the_resources_it_asks_for() -> None:
    """A missing resource fails here rather than on the first partition of a backfill."""
    Definitions.validate_loadable(defs)
