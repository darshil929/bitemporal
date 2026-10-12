from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import date

import httpx
import pytest
from sqlalchemy import text

from api.config import ApiSettings
from api.db.database import Database
from api.services.readiness import EXPECTED_REVISION

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

HDFC_BANK = "INE040A01034"
LAST_DAY = date(2025, 12, 31)

FEATURE_AND_BAR = text(
    "select features.primary_venue, features.close, bars.close as bar_close"
    " from mart_daily_features as features"
    " join stg_price_daily as bars on bars.isin = features.isin"
    " and bars.venue = features.primary_venue and bars.trade_date = features.trade_date"
    " where features.isin = :isin and features.trade_date = :day"
)

INSTRUMENTS_ON_THE_DAY = text(
    "select (select count(*) from mart_daily_features where trade_date = :day),"
    " (select count(distinct isin) from int_continuous_prices where trade_date = :day)"
)


@pytest.fixture
async def database(dataset_settings: ApiSettings) -> AsyncIterator[Database]:
    opened = Database(dataset_settings)
    yield opened
    await opened.close()


async def test_the_api_is_ready_over_the_seed_dataset(
    start_api: StartApi, dataset_settings: ApiSettings
) -> None:
    async with start_api(dataset_settings) as api:
        response = await api.get("/ready")

    assert response.status_code == 200
    assert response.json()["migration"] == EXPECTED_REVISION


async def test_a_daily_feature_row_closes_where_its_primary_venue_closed(
    database: Database,
) -> None:
    async with database.transaction() as session:
        row = (await session.execute(FEATURE_AND_BAR, {"isin": HDFC_BANK, "day": LAST_DAY})).one()

    assert row.primary_venue in {"BSE", "NSE"}
    assert row.close == row.bar_close


async def test_each_instrument_trading_on_the_last_day_has_its_daily_features(
    database: Database,
) -> None:
    async with database.transaction() as session:
        features, instruments = (
            await session.execute(INSTRUMENTS_ON_THE_DAY, {"day": LAST_DAY})
        ).one()

    assert instruments > 0
    assert features == instruments
