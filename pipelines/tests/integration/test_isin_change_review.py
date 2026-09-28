"""The reviewed changes of ISIN are checked against the history the database holds."""

import os
import subprocess
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config

from conftest import MIGRATION_SCHEMA, PointedDatabase
from pipelines.facts import persist_bars
from pipelines.identity import persist_identity
from pipelines.models.identity import InstrumentRecord
from pipelines.models.market import PriceBar

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"
CHECK = "assert_unadjusted_changes_name_a_change_of_isin"

# Reviewed in unadjusted_changes_of_isin: this ISIN took its instrument over on 2025-10-15.
SUCCESSOR = "INE947T01022"


def dbt(dsn: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run dbt against the schema the tests migrate, in the test container."""
    url = urlsplit(dsn)
    env = {
        **os.environ,
        "POSTGRES_HOST": url.hostname or "",
        "POSTGRES_PORT": str(url.port),
        "POSTGRES_USER": url.username or "",
        "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_DB": url.path.lstrip("/"),
    }
    command = ["dbt", *arguments, "--profiles-dir", ".", "--target", MIGRATION_SCHEMA]
    return subprocess.run(
        command, cwd=DBT_DIR, env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def built(migrated: Config, postgres_dsn: str) -> Iterator[None]:
    yield
    # The models are views over the migrated tables, which cannot be dropped while they stand.
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        views = connection.execute(
            "select table_name from information_schema.views where table_schema = %s",
            (MIGRATION_SCHEMA,),
        ).fetchall()
        for (view,) in views:
            connection.execute(
                psycopg.sql.SQL("drop view if exists {}.{} cascade").format(
                    psycopg.sql.Identifier(MIGRATION_SCHEMA), psycopg.sql.Identifier(view)
                )
            )
        connection.execute(
            psycopg.sql.SQL("drop table if exists {}.unadjusted_changes_of_isin").format(
                psycopg.sql.Identifier(MIGRATION_SCHEMA)
            )
        )


def test_a_change_before_the_history_held_is_not_asked_for(built: None, postgres_dsn: str) -> None:
    """A bootstrap reads the two most recent years first, holding a successor traded since and
    neither side of its change.
    """
    close = Decimal("100.00")
    database = PointedDatabase(dsn=postgres_dsn)
    with database.connect() as connection:
        persist_identity(
            connection,
            [
                InstrumentRecord(
                    isin=SUCCESSOR, name=SUCCESSOR, country="IN", instrument_type="equity"
                )
            ],
            (),
            (),
        )
        persist_bars(
            connection,
            [
                PriceBar(
                    isin=SUCCESSOR,
                    venue="NSE",
                    trade_date=date(2026, 9, 25),
                    as_of_date=date(2026, 9, 25),
                    local_symbol=SUCCESSOR,
                    scrip_code=None,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    previous_close=None,
                    volume=100,
                    turnover=None,
                    trade_count=None,
                )
            ],
        )
        connection.commit()

    checked = dbt(
        postgres_dsn,
        "build",
        "--select",
        f"+{CHECK}",
        "--exclude",
        "test_type:unit",
        "--indirect-selection",
        "empty",
    )

    assert checked.returncode == 0, checked.stdout[-3000:]
