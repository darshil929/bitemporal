"""The day the market pages show, each venue's verdict on it, and the last day complete everywhere."""

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from api.services import market_reads
from fixtures.database import MIGRATION_SCHEMA

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]

# The verdicts as the trading days mart presents them, one per venue and day.
TRADING_DAYS = (
    "create view mart_trading_days as select venue, trade_date, as_of_date, is_complete, bars,"
    " divergent_instruments, detail from trading_day"
)
VERDICT = (
    "insert into trading_day"
    " (venue, trade_date, as_of_date, is_complete, bars, divergent_instruments, detail)"
    " values (%s, %s, %s, %s, 2500, 0, %s)"
)
RELEASE = (
    "insert into feature_release (table_name, trade_date, row_count)"
    " values ('daily_features_a', %s, 2500)"
)
BOTH_COMPLETE = [{"venue": "BSE", "is_complete": True}, {"venue": "NSE", "is_complete": True}]
NO_DAY = {"published_day": None, "published_at": None, "venues": [], "last_complete_day": None}


class Market:
    """Day verdicts and feature releases the tables' owner writes in the migrated schema, and the
    day the API shows a member over them."""

    def __init__(
        self, dsn: str, start_api: StartApi, settings: ApiSettings, headers: dict[str, str]
    ) -> None:
        self.dsn, self.start_api, self.settings, self.headers = dsn, start_api, settings, headers

    def execute(self, statement: str, values: tuple[Any, ...] = ()) -> None:
        options = f"-csearch_path={MIGRATION_SCHEMA},public"
        with psycopg.connect(self.dsn, options=options, autocommit=True) as owner:
            owner.execute(statement, values)

    def session(self, day: str, **venues: bool) -> None:
        """Each named venue's verdict on the day: complete or not."""
        for venue, is_complete in venues.items():
            detail = None if is_complete else "fewer bars than the days before"
            self.execute(VERDICT, (venue, day, day, is_complete, detail))

    def build_trading_days(self) -> None:
        self.execute(TRADING_DAYS)
        self.execute("grant select on mart_trading_days to bitemporal_api")

    async def day(self, signed_in: bool = True) -> httpx.Response:
        async with self.start_api(self.settings) as api:
            return await api.get("/market/day", headers=self.headers if signed_in else {})


@pytest.fixture
def market(
    start_api: StartApi,
    migrated_settings: ApiSettings,
    member_headers: dict[str, str],
    postgres_dsn: str,
) -> Iterator[Market]:
    written = Market(postgres_dsn, start_api, migrated_settings, member_headers)
    yield written
    written.execute("drop view if exists mart_trading_days")


async def test_the_seed_dataset_shows_its_last_day_complete_at_both_venues(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> None:
    async with start_api(dataset_settings) as api:
        response = await api.get("/market/day", headers=dataset_member_headers)

    body = response.json()
    assert response.status_code == 200
    assert (body["published_day"], body["last_complete_day"]) == ("2025-12-31", "2025-12-31")
    assert body["venues"] == BOTH_COMPLETE
    assert body["published_at"] is not None


async def test_before_the_first_publish_no_day_is_shown(market: Market) -> None:
    response = await market.day()

    assert (response.status_code, response.json()) == (200, NO_DAY)


async def test_a_venue_left_incomplete_holds_the_complete_day_to_the_day_before(
    market: Market,
) -> None:
    market.session("2025-12-30", BSE=True, NSE=True)
    market.session("2025-12-31", BSE=True, NSE=False)
    market.execute(RELEASE, ("2025-12-31",))
    market.build_trading_days()

    body = (await market.day()).json()

    assert body["published_day"] == "2025-12-31"
    assert body["venues"] == [
        {"venue": "BSE", "is_complete": True},
        {"venue": "NSE", "is_complete": False},
    ]
    assert body["last_complete_day"] == "2025-12-30"


async def test_a_session_one_venue_held_alone_is_complete_on_its_verdict(market: Market) -> None:
    market.session("2025-10-17", BSE=True, NSE=True)
    market.session("2025-10-18", BSE=True)
    market.execute(RELEASE, ("2025-10-18",))
    market.build_trading_days()

    body = (await market.day()).json()

    assert body["venues"] == [{"venue": "BSE", "is_complete": True}]
    assert body["last_complete_day"] == "2025-10-18"


async def test_a_mart_built_again_during_the_wait_is_read_on_the_second_attempt(
    market: Market, monkeypatch: pytest.MonkeyPatch
) -> None:
    market.session("2025-12-31", BSE=True, NSE=True)
    market.execute(RELEASE, ("2025-12-31",))

    async def rebuilt() -> None:
        market.build_trading_days()

    monkeypatch.setattr(market_reads, "wait_for_rebuild", rebuilt)

    response = await market.day()

    assert response.status_code == 200
    assert response.json()["venues"] == BOTH_COMPLETE


async def test_a_mart_still_absent_after_the_wait_answers_that_figures_are_updating(
    market: Market, monkeypatch: pytest.MonkeyPatch
) -> None:
    market.execute(RELEASE, ("2025-12-31",))
    waits: list[None] = []

    async def waited() -> None:
        waits.append(None)

    monkeypatch.setattr(market_reads, "wait_for_rebuild", waited)

    response = await market.day()

    assert (response.status_code, len(waits)) == (503, 1)
    assert response.json() == {"detail": {"reason": "market_data_updating"}}
    assert response.headers["retry-after"] == "5"


async def test_market_reads_are_refused_without_a_session(market: Market) -> None:
    response = await market.day(signed_in=False)

    assert response.status_code == 401
