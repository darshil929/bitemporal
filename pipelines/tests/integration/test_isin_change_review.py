"""The reviewed changes of ISIN are checked against the history the database holds."""

import os
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import MIGRATION_SCHEMA, PointedDatabase, dbt_environment
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
    command = ["dbt", *arguments, "--profiles-dir", ".", "--target", MIGRATION_SCHEMA]
    return subprocess.run(
        command,
        cwd=DBT_DIR,
        env={**os.environ, **dbt_environment(dsn)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_change_before_the_history_held_is_not_asked_for(
    dbt_built: None, postgres_dsn: str
) -> None:
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
