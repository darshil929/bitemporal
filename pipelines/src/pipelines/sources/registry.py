"""Source definitions, loaded from configuration and mirrored into the database."""

import tomllib
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import psycopg
from pydantic import BaseModel, Field

from pipelines.sources.errors import UnknownSchemaVersion

SOURCES_FILE = Path(__file__).resolve().parents[1] / "config" / "sources.toml"


class SchemaVersion(BaseModel):
    version: str
    effective_from: date
    effective_to: date | None = None

    def covers(self, partition: date) -> bool:
        if partition < self.effective_from:
            return False
        return self.effective_to is None or partition <= self.effective_to


class SourceDefinition(BaseModel):
    source_id: str
    tier: int = Field(ge=1, le=4)
    base_url: str
    requests_per_second: float = Field(gt=0)
    cache_policy: str
    sebi_curation_ref: str | None = None
    owner_notes: str | None = None
    schema_version: tuple[SchemaVersion, ...] = ()

    def version_for(self, partition: date) -> str:
        for candidate in self.schema_version:
            if candidate.covers(partition):
                return candidate.version
        raise UnknownSchemaVersion(
            f"{self.source_id} has no schema version covering {partition.isoformat()}"
        )


def load_definitions(path: Path = SOURCES_FILE) -> tuple[SourceDefinition, ...]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return tuple(SourceDefinition.model_validate(entry) for entry in document["source"])


def sync_registry(connection: psycopg.Connection, definitions: Sequence[SourceDefinition]) -> None:
    """Write the definitions into source_registry, replacing what is recorded for each source."""
    for definition in definitions:
        connection.execute(
            "insert into source_registry (source_id, tier, sebi_curation_ref, base_url,"
            " requests_per_second, cache_policy, owner_notes)"
            " values (%s, %s, %s, %s, %s, %s, %s)"
            " on conflict (source_id) do update set"
            " tier = excluded.tier,"
            " sebi_curation_ref = excluded.sebi_curation_ref,"
            " base_url = excluded.base_url,"
            " requests_per_second = excluded.requests_per_second,"
            " cache_policy = excluded.cache_policy,"
            " owner_notes = excluded.owner_notes",
            (
                definition.source_id,
                definition.tier,
                definition.sebi_curation_ref,
                definition.base_url,
                definition.requests_per_second,
                definition.cache_policy,
                definition.owner_notes,
            ),
        )
        connection.execute(
            "delete from source_schema_version where source_id = %s", (definition.source_id,)
        )
        for version in definition.schema_version:
            connection.execute(
                "insert into source_schema_version"
                " (source_id, version, effective_from, effective_to) values (%s, %s, %s, %s)",
                (
                    definition.source_id,
                    version.version,
                    version.effective_from,
                    version.effective_to,
                ),
            )
