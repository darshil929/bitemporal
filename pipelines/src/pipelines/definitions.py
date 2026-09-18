"""Dagster entry point exposing the asset definitions."""

from dagster import Definitions, load_assets_from_package_module

from pipelines import assets
from pipelines.resources import Bhavcopies, Database

defs = Definitions(
    assets=load_assets_from_package_module(assets),
    resources={"database": Database(), "bhavcopies": Bhavcopies()},
)
