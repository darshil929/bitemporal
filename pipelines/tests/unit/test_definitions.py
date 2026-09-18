"""The Dagster entry point loads, carrying the assets and the resources they ask for."""

from dagster import Definitions

from pipelines.definitions import defs


def test_definitions_loads() -> None:
    assert isinstance(defs, Definitions)


def test_both_venues_are_ingested_by_trading_day() -> None:
    keys = {key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()}

    assert {"bse_bhavcopy", "nse_bhavcopy"} <= keys


def test_every_asset_finds_the_resources_it_asks_for() -> None:
    """A missing resource fails here rather than on the first partition of a backfill."""
    Definitions.validate_loadable(defs)
