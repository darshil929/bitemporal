"""The dbt project as assets, one per model, downstream of the assets that fill its sources.

Each model becomes its own step, so a failed dbt test blocks what reads that model rather than
the whole run, and the graph shows which table a number came from.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AssetKey, AssetSpec
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from pipelines.config.settings import DatabaseSettings

DBT_DIR = Path(__file__).resolve().parents[4] / "dbt"

BSE = AssetKey("bse_bhavcopy")
NSE = AssetKey("nse_bhavcopy")
IDENTITY = AssetKey("instrument_identity")
COMPLETENESS = AssetKey("trading_day_completeness")

# Which asset fills each table the models read. Delivery and corporate actions are ingested by
# scripts rather than assets so far, so they stand in the graph with nothing upstream of them.
SOURCE_WRITERS: dict[str, list[AssetKey]] = {
    "price_daily": [BSE, NSE],
    "instrument_master": [BSE, NSE, IDENTITY],
    "listing": [IDENTITY],
    "trading_day": [COMPLETENESS],
    "delivery_daily": [],
    "corporate_action": [],
}

dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)

# A manifest is what the models are read from, and it is a build artefact rather than a committed
# file. Parsing when it is absent means a fresh checkout loads without a separate build step.
if not dbt_project.manifest_path.exists():
    dbt_project.preparer.prepare(dbt_project)


def source_assets() -> list[AssetSpec]:
    """The tables the models read, each carrying the assets that write it."""
    return [
        AssetSpec(
            key=AssetKey(["market", table]),
            deps=writers,
            description=f"The {table} table, read by the dbt models.",
        )
        for table, writers in SOURCE_WRITERS.items()
    ]


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project)
def dbt_models(context: AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
    yield from dbt.cli(["build", "--target", DatabaseSettings().data_env], context=context).stream()
