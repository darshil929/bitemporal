"""An instrument's newest day at one venue as its key figures show it, read over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
KeyFigures = Callable[..., Awaitable[httpx.Response]]

HDFC_BANK = "INE040A01034"
SPICEJET = "INE285B01017"
PIRAMAL_ENTERPRISES = "INE140A01024"
LAST_DAY = "2025-12-31"

BAR = (
    "select open, close, previous_close, volume, trade_count from mart_price_daily"
    " where isin = %s and venue = %s and trade_date = %s"
)
VENUE_FIGURES = (
    "select change_1d, return_1d from mart_venue_daily_figures"
    " where isin = %s and venue = %s and trade_date = %s"
)
FEATURES = (
    "select primary_venue, change_1d, return_1d from mart_daily_features"
    " where isin = %s and trade_date = %s"
)


def sources(body: dict[str, Any]) -> list[tuple[str, int]]:
    return [(source["source_id"], source["tier"]) for source in body["sources"]]


@pytest.fixture
def key_figures(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> KeyFigures:
    async def reading(isin: str, venue: str, signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get(
                f"/instruments/{isin}/day", params={"venue": venue}, headers=headers
            )

    return reading


@pytest.mark.parametrize("venue", ["BSE", "NSE"])
async def test_the_newest_day_reads_as_traded_with_its_change_on_the_adjusted_series(
    key_figures: KeyFigures, seeded_models: psycopg.Connection, venue: str
) -> None:
    bar = seeded_models.execute(BAR, (HDFC_BANK, venue, LAST_DAY)).fetchone()
    figures = seeded_models.execute(VENUE_FIGURES, (HDFC_BANK, venue, LAST_DAY)).fetchone()
    features = seeded_models.execute(FEATURES, (HDFC_BANK, LAST_DAY)).fetchone()
    other = "NSE" if venue == "BSE" else "BSE"

    body = (await key_figures(HDFC_BANK, venue)).json()

    assert bar is not None and figures is not None and features is not None
    assert (
        body["trade_date"],
        body["is_stale"],
        body["trading_days_behind"],
        body["is_day_complete"],
    ) == (LAST_DAY, False, 0, True)
    shown = (
        body["open"],
        body["close"],
        body["previous_close"],
        body["volume"],
        body["trade_count"],
    )
    assert shown == (float(bar[0]), float(bar[1]), float(bar[2]), bar[3], bar[4])
    assert (body["change_1d"], body["return_1d"]) == figures
    if features[0] == venue:
        assert (body["change_1d"], body["return_1d"]) == features[1:]
    assert body["venue_spread_bps"] is not None and body["is_diverging"] is False
    assert sources(body) == [
        (f"{venue.lower()}_bhavcopy_equity", 1),
        (f"{venue.lower()}_delivery", 1),
        (f"{other.lower()}_bhavcopy_equity", 1),
    ]


async def test_a_single_listed_instrument_has_no_spread(key_figures: KeyFigures) -> None:
    body = (await key_figures(SPICEJET, "BSE")).json()

    assert body["venue_spread_bps"] is None
    assert sources(body) == [("bse_bhavcopy_equity", 1), ("bse_delivery", 1)]


async def test_a_day_older_than_the_published_one_is_stale_by_the_venues_trading_days(
    key_figures: KeyFigures,
) -> None:
    body = (await key_figures(PIRAMAL_ENTERPRISES, "NSE")).json()

    assert (body["trade_date"], body["is_stale"], body["trading_days_behind"]) == (
        "2025-09-22",
        True,
        68,
    )
    assert body["delivery_pct_1d"] is None
    assert sources(body) == [("nse_bhavcopy_equity", 1), ("bse_bhavcopy_equity", 1)]


async def test_a_venue_the_instrument_never_traded_at_has_no_figures(
    key_figures: KeyFigures,
) -> None:
    body = (await key_figures(SPICEJET, "NSE")).json()

    assert (body["trade_date"], body["close"], body["trading_days_behind"], body["sources"]) == (
        None,
        None,
        None,
        [],
    )


async def test_an_unknown_isin_is_not_found(key_figures: KeyFigures) -> None:
    response = await key_figures("INE999Z01019", "NSE")

    assert response.status_code == 404
    assert response.json() == {"detail": {"reason": "instrument_not_found"}}


async def test_key_figures_are_refused_without_a_session(key_figures: KeyFigures) -> None:
    assert (await key_figures(HDFC_BANK, "NSE", signed_in=False)).status_code == 401
