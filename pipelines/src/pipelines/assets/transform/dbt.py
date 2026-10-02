"""The dbt project as assets, one per model, downstream of the assets that fill its sources.

Each model becomes its own asset, so the graph shows which table a number came from. Each table
the models read is an asset of its own, run once every asset writing it has, so a run builds the
models last.
"""

import signal
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AssetKey, AssetsDefinition, MaterializeResult, asset
from dagster_dbt import DbtCliInvocation, DbtCliResource, DbtProject, dbt_assets
from psycopg import sql

from pipelines.config.settings import DatabaseSettings
from pipelines.resources import Database

DBT_DIR = Path(__file__).resolve().parents[4] / "dbt"

# How long an interrupted dbt command has to cancel its queries and exit before it is killed.
STOP_SECONDS = 30.0

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

# Folders dbt writes inside the project and never reads when parsing it.
BUILD_FOLDERS = frozenset({"target", "logs", "dbt_packages"})


def project_paths(project_dir: Path) -> Iterator[Path]:
    """Every file and folder of the dbt project, leaving out what dbt writes there itself."""
    for entry in project_dir.iterdir():
        if entry.name in BUILD_FOLDERS or entry.name.startswith("."):
            continue
        yield entry
        if entry.is_dir():
            yield from entry.rglob("*")


def manifest_is_current(project: DbtProject) -> bool:
    """Whether the manifest exists and nothing in the project changed after it was parsed.

    A folder's modification time moves when an entry is added to it or removed from it, so a
    model deleted since the parse counts as a change.
    """
    if not project.manifest_path.exists():
        return False
    parsed_at = project.manifest_path.stat().st_mtime
    return all(path.stat().st_mtime <= parsed_at for path in project_paths(project.project_dir))


def prepare(project: DbtProject) -> None:
    """Parse the project into its manifest unless the manifest is current."""
    if not manifest_is_current(project):
        project.preparer.prepare(project)


dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)

# The models are read from the manifest, a build artefact rather than a committed file, so a
# checkout that adds, changes or removes a model or test loads it only once the project is parsed.
prepare(dbt_project)


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


def dbt_commands(target: str) -> list[list[str]]:
    """Seeds and models one at a time, then every test in parallel.

    Postgres replaces a view by renaming the old one and dropping it with every view built on it, so
    two views replaced at once lock the views they share in opposite orders and deadlock.
    """
    return [
        ["seed", "--target", target, "--threads", "1"],
        ["run", "--target", target, "--threads", "1"],
        ["test", "--target", target],
    ]


def stop(process: subprocess.Popen[bytes]) -> None:
    """Interrupt a dbt process still running, which cancels its queries, and kill it if it stays."""
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=STOP_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def stream(invocation: DbtCliInvocation) -> Iterator[Any]:
    """The events of one dbt command, which ends with the step that reads them.

    dagster-dbt stops dbt only when a run is cancelled; on any other failure the step exits and
    dbt runs on, writing to the database with nothing reading its output.
    """
    try:
        yield from invocation.stream()
    finally:
        stop(invocation.process)


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project)
def dbt_models(context: AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
    for command in dbt_commands(DatabaseSettings().data_env):
        yield from stream(dbt.cli(command, context=context))
