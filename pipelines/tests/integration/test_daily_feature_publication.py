"""A run publishes the daily features it computed once every check on them has passed."""

from collections.abc import Iterator

import numpy as np
import psycopg
import pytest
from alembic.config import Config
from dagster import (
    AssetChecksDefinition,
    AssetKey,
    AssetsDefinition,
    ExecuteInProcessResult,
    MaterializeResult,
    asset,
    materialize,
)

from fixtures.database import MIGRATION_SCHEMA, PointedDatabase
from pipelines.assets.features.publication import daily_feature_publication
from pipelines.checks.features import daily_feature_ranges
from pipelines.daily_features import ENGINE_COLUMNS, DailyFeatureRows, write_daily_features
from pipelines.feature_publication import published_table, unpublished_table
from pipelines.resources import Database

HDFC_BANK = "INE040A01034"


def computation(rsi: float) -> AssetsDefinition:
    """The daily features asset, writing one row whose RSI is `rsi`."""

    @asset(key=AssetKey("daily_features"))
    def computed(database: Database) -> MaterializeResult[None]:
        figures = np.full((len(ENGINE_COLUMNS), 1), np.nan)
        figures[ENGINE_COLUMNS.index("rsi_14")] = rsi
        rows = DailyFeatureRows(
            isin=[HDFC_BANK],
            trade_date=np.array(["2025-12-31"], dtype="datetime64[D]"),
            as_of_date=np.array(["2025-12-31"], dtype="datetime64[D]"),
            primary_venue=["NSE"],
            close=np.array([991.2]),
            figures=figures,
            venue_spread_bps=np.array([np.nan]),
            is_day_complete=np.array([True]),
            is_diverging=np.array([False]),
        )
        with database.connect() as connection:
            table = unpublished_table(connection)
            write_daily_features(connection, [rows], table)
        return MaterializeResult(metadata={"table": table})

    return computed


@pytest.fixture
def connection(migrated: Config, postgres_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as open_:
        open_.execute(
            "insert into instrument_master (isin, name, country, instrument_type)"
            " values (%s, 'HDFC Bank', 'IN', 'equity')",
            (HDFC_BANK,),
        )
        open_.execute(
            "create table venue_delivery_discrepancies"
            " (venue varchar(12), trade_date date, reason text)"
        )
        open_.commit()
        yield open_
        open_.rollback()
        open_.execute("drop table venue_delivery_discrepancies")
        open_.commit()


def run(
    postgres_dsn: str, *steps: AssetsDefinition | AssetChecksDefinition
) -> ExecuteInProcessResult:
    return materialize(
        steps, resources={"database": PointedDatabase(dsn=postgres_dsn)}, raise_on_error=False
    )


def releases(connection: psycopg.Connection) -> list[tuple[object, ...]]:
    return connection.execute("select table_name, run_id from feature_release").fetchall()


def test_a_computation_passing_every_check_is_published(
    connection: psycopg.Connection, postgres_dsn: str
) -> None:
    result = run(postgres_dsn, computation(48.3), daily_feature_ranges, daily_feature_publication)

    assert result.success
    assert published_table(connection) == "daily_features_b"
    assert releases(connection) == [("daily_features_b", result.run_id)]


def test_a_computation_failing_a_check_is_not_published(
    connection: psycopg.Connection, postgres_dsn: str
) -> None:
    result = run(postgres_dsn, computation(101.0), daily_feature_ranges, daily_feature_publication)

    failed = [event.step_key for event in result.get_step_failure_events()]
    published = result.asset_materializations_for_node("daily_feature_publication")
    assert failed == ["daily_feature_ranges"]
    assert published == []
    assert published_table(connection) == "daily_features_a"
    assert releases(connection) == []


def test_nothing_is_published_without_a_computation_in_the_run(
    connection: psycopg.Connection, postgres_dsn: str
) -> None:
    assert not run(postgres_dsn, daily_feature_publication).success

    assert published_table(connection) == "daily_features_a"
