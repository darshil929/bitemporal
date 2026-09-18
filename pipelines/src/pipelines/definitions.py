"""Dagster entry point exposing the asset definitions."""

from dagster import (
    Definitions,
    load_asset_checks_from_package_module,
    load_assets_from_package_module,
)

from pipelines import assets, checks
from pipelines.resources import Bhavcopies, Database

defs = Definitions(
    assets=load_assets_from_package_module(assets),
    asset_checks=load_asset_checks_from_package_module(checks),
    resources={"database": Database(), "bhavcopies": Bhavcopies()},
)
