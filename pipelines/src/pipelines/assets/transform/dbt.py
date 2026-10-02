"""The dbt project as assets, one per model, downstream of the assets that fill its sources.

Each model becomes its own step, so a failed dbt test blocks what reads that model rather than
the whole run, and the graph shows which table a number came from. Each table the models read is
an asset of its own, run once every asset writing it has, so a run builds the models last.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AssetKey, AssetsDefinition, MaterializeResult, asset
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets
from psycopg import sql

from pipelines.config.settings import DatabaseSettings
from pipelines.resources import Database

DBT_DIR = Path(__file__).resolve().parents[4] / "dbt"

BSE = AssetKey("bse_bhavcopy")
NSE = AssetKey("nse_bhavcopy")
IDENTITY = AssetKey("instrument_identity")
COMPLETENESS = AssetKey("trading_day_completeness")
ACTIONS = [AssetKey("corporate_actions"), AssetKey("nse_corporate_actions")]
DELIVERY = [AssetKey("bse_delivery"), AssetKey("nse_delivery")]
NAMES = [AssetKey("bse_instrument_names"), AssetKey("nse_instrument_names")]

# Which asset fills each table the models read.
SOURCE_WRITERS: dict[str, list[AssetKey]] = {
    "price_daily": [BSE, NSE],
    "instrument_master": [BSE, NSE, IDENTITY],
    "listing": [IDENTITY],
    "instrument_succession": [IDENTITY],
    "trading_day": [COMPLETENESS],
    "delivery_daily": DELIVERY,
    "corporate_action": ACTIONS,
    "instrument_name": NAMES,
}

dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)

# A manifest is what the models are read from, and it is a build artefact rather than a committed
# file. Parsing when it is absent means a fresh checkout loads without a separate build step.
if not dbt_project.manifest_path.exists():
    dbt_project.preparer.prepare(dbt_project)


def table_assets() -> list[AssetsDefinition]:
    """The tables the models read, each after the assets that write it.

    A table declared only as a source is not a step a job can run, so a job would hold nothing
    between the assets writing a table and the models reading it, and would start the models first.
    """
    return [table_asset(table, writers) for table, writers in SOURCE_WRITERS.items()]


def table_asset(table: str, writers: list[AssetKey]) -> AssetsDefinition:
    @asset(
        key=AssetKey(["market", table]),
        deps=writers,
        group_name="market",
        description=f"The {table} table as its writers left it for the models.",
    )
    def written(database: Database) -> MaterializeResult[None]:
        with database.connect() as connection:
            counted = connection.execute(
                sql.SQL("select count(*) from {}").format(sql.Identifier(table))
            ).fetchone()
        return MaterializeResult(metadata={"rows": int(counted[0]) if counted else 0})

    return written


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project)
def dbt_models(context: AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
    yield from dbt.cli(["build", "--target", DatabaseSettings().data_env], context=context).stream()
