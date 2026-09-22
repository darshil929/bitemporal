"""Dagster entry point exposing the asset definitions."""

from dagster import (
    Definitions,
    load_asset_checks_from_package_module,
    load_assets_from_package_module,
)
from dagster_dbt import DbtCliResource

from pipelines import assets, checks
from pipelines.assets.transform.dbt import dbt_project, source_assets
from pipelines.resources import Bhavcopies, CorporateActions, Database, Deliveries

defs = Definitions(
    assets=[*load_assets_from_package_module(assets), *source_assets()],
    asset_checks=load_asset_checks_from_package_module(checks),
    resources={
        "database": Database(),
        "bhavcopies": Bhavcopies(),
        "actions": CorporateActions(),
        "deliveries": Deliveries(),
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)
