"""Each table the models read records how many rows its writers left in it."""

from datetime import date
from decimal import Decimal

from alembic.config import Config

from conftest import PointedDatabase
from pipelines.assets.transform.dbt import table_asset
from pipelines.facts import persist_bars
from pipelines.identity import persist_identity
from pipelines.models.identity import InstrumentRecord
from pipelines.models.market import PriceBar

HDFC_BANK = "INE040A01034"
CLOSE = Decimal("1900.00")


def bar(venue: str) -> PriceBar:
    return PriceBar(
        isin=HDFC_BANK,
        venue=venue,
        trade_date=date(2026, 9, 25),
        as_of_date=date(2026, 9, 25),
        local_symbol="HDFCBANK",
        scrip_code=None,
        open=CLOSE,
        high=CLOSE,
        low=CLOSE,
        close=CLOSE,
        previous_close=None,
        volume=1000,
        turnover=None,
        trade_count=None,
    )


def test_a_table_records_the_rows_its_writers_left(migrated: Config, postgres_dsn: str) -> None:
    database = PointedDatabase(dsn=postgres_dsn)
    instrument = InstrumentRecord(
        isin=HDFC_BANK, name="HDFC Bank", country="IN", instrument_type="equity"
    )
    with database.connect() as connection:
        persist_identity(connection, [instrument], ())
        persist_bars(connection, [bar("BSE"), bar("NSE")])
        connection.commit()

    result = table_asset("price_daily", [])(database=database)

    assert result.metadata == {"rows": 2}
