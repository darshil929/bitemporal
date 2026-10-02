"""Dagster entry point exposing the asset definitions."""

from dagster import (
    Definitions,
    load_asset_checks_from_package_module,
    load_assets_from_package_module,
)
from dagster_dbt import DbtCliResource

from pipelines import assets, checks
from pipelines.assets.transform.dbt import dbt_project, table_assets
from pipelines.jobs import daily_sync, history_bootstrap
from pipelines.resources import (
    Bhavcopies,
    CorporateActions,
    Database,
    Deliveries,
    NseActions,
    NseLists,
    ScripLists,
)
from pipelines.schedules import daily_sync_schedule

defs = Definitions(
    assets=[*load_assets_from_package_module(assets), *table_assets()],
    asset_checks=load_asset_checks_from_package_module(checks),
    jobs=[history_bootstrap, daily_sync],
    schedules=[daily_sync_schedule],
    resources={
        "database": Database(),
        "bhavcopies": Bhavcopies(),
        "actions": CorporateActions(),
        "nse_actions": NseActions(),
        "deliveries": Deliveries(),
        "scrip_lists": ScripLists(),
        "nse_lists": NseLists(),
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)
