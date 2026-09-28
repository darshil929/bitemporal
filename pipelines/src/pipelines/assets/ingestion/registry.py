"""The sources the pipelines read and the formats each has published, written from configuration.

Every flow writes the registry before reading a source, so the database describes the sources its
facts came from.
"""

from dagster import AssetExecutionContext, MaterializeResult, asset

from pipelines.resources import Database
from pipelines.sources.registry import load_definitions, sync_registry

GROUP = "ingestion"


@asset(
    group_name=GROUP,
    description="Every registered source and the date range of each format it has published.",
)
def source_registry(context: AssetExecutionContext, database: Database) -> MaterializeResult[None]:
    definitions = load_definitions()
    with database.connect() as connection:
        sync_registry(connection, definitions)
        connection.commit()

    context.log.info("source registry written", extra={"sources": len(definitions)})
    return MaterializeResult(metadata={"sources": len(definitions)})
