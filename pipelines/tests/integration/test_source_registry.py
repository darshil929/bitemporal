"""Registered sources reach the database and survive being written again."""

import psycopg
import pytest

from pipelines.sources.registry import load_definitions, sync_registry


def test_every_configured_source_reaches_the_registry(
    migrated_connection: psycopg.Connection,
) -> None:
    definitions = load_definitions()

    sync_registry(migrated_connection, definitions)
    stored = migrated_connection.execute("select source_id, tier from source_registry").fetchall()

    assert {row[0] for row in stored} == {item.source_id for item in definitions}
    assert all(1 <= row[1] <= 4 for row in stored)


def test_schema_versions_are_stored_per_source(
    migrated_connection: psycopg.Connection,
) -> None:
    definitions = load_definitions()

    sync_registry(migrated_connection, definitions)
    versions = migrated_connection.execute(
        "select source_id, version from source_schema_version order by source_id, version"
    ).fetchall()

    expected = sorted(
        (definition.source_id, version.version)
        for definition in definitions
        for version in definition.schema_version
    )
    assert [(row[0], row[1]) for row in versions] == expected


def test_writing_the_registry_again_leaves_one_row_per_source(
    migrated_connection: psycopg.Connection,
) -> None:
    """Reloading configuration must not accumulate duplicate versions."""
    definitions = load_definitions()

    sync_registry(migrated_connection, definitions)
    sync_registry(migrated_connection, definitions)

    sources = migrated_connection.execute("select count(*) from source_registry").fetchone()
    versions = migrated_connection.execute("select count(*) from source_schema_version").fetchone()

    assert sources is not None and sources[0] == len(definitions)
    assert versions is not None and versions[0] == sum(
        len(definition.schema_version) for definition in definitions
    )


def test_a_version_cannot_name_a_source_outside_the_registry(
    migrated_connection: psycopg.Connection,
) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        migrated_connection.execute(
            "insert into source_schema_version (source_id, version, effective_from)"
            " values (%s, %s, %s)",
            ("not_registered", "udiff", "2024-07-08"),
        )
