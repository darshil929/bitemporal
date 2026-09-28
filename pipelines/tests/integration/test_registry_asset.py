"""The source registry is written from configuration before any source is read."""

import psycopg
from alembic.config import Config
from dagster import build_asset_context

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.ingestion.registry import source_registry
from pipelines.sources.registry import load_definitions


def test_the_registry_is_written_from_configuration_once(
    migrated: Config, postgres_dsn: str
) -> None:
    """Every flow writes it, so writing it again leaves one row per source and format."""
    definitions = load_definitions()
    database = PointedDatabase(dsn=postgres_dsn)

    source_registry(build_asset_context(), database)
    result = source_registry(build_asset_context(), database)

    with psycopg.connect(
        postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public"
    ) as connection:
        sources = connection.execute("select count(*) from source_registry").fetchone()
        versions = connection.execute("select count(*) from source_schema_version").fetchone()
    assert sources == (len(definitions),)
    assert versions == (sum(len(item.schema_version) for item in definitions),)
    assert result.metadata["sources"] == len(definitions)
