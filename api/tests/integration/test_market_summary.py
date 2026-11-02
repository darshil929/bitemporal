"""Breadth and the companies that moved most, read over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import date
from statistics import median
from typing import Any

import httpx
import psycopg
import pytest

from api.config import ApiSettings
from api.services import market_summary

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
Summary = Callable[..., Awaitable[httpx.Response]]

DAY = date(2025, 12, 31)
GATE = 250_000_000
COMPANIES = (
    "select isin, return_1d, adtv_20d, is_52w_high, is_52w_low from mart_daily_features"
    " where trade_date = %s and isin like 'INE%%'"
)
UNHANDLED = (
    "select ex_date, purpose from mart_corporate_actions where isin = %s"
    " and action_type = 'unhandled' and ex_date > %s and ex_date <= %s"
    " order by ex_date desc, purpose"
)
BAR_BACK = (
    "select trade_date from mart_adjusted_prices where isin = %s and venue = %s and trade_date <= %s"
    " order by trade_date desc offset %s limit 1"
)


@pytest.fixture
def summary(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Summary:
    async def read(signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get("/market/summary", headers=headers)

    return read


def companies(models: psycopg.Connection) -> list[tuple[Any, ...]]:
    return models.execute(COMPANIES, (DAY,)).fetchall()


def ranked(models: psycopg.Connection, sign: int) -> list[tuple[Any, ...]]:
    """The day's moves of one sign, largest first, ties in ISIN order."""
    moves = [row for row in companies(models) if row[1] is not None and row[1] * sign > 0]
    return sorted(moves, key=lambda row: (-abs(row[1]), row[0]))


def past_gate(moves: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [row for row in moves if row[2] is not None and row[2] >= GATE]


def below_gate_beyond(moves: list[tuple[Any, ...]], last: float | None) -> list[str]:
    """The ISINs below the gate that moved further than the last mover, largest first."""
    return [
        row[0]
        for row in moves
        if row[2] is not None and row[2] < GATE and (last is None or abs(row[1]) > abs(last))
    ]


async def test_breadth_counts_the_companies_that_traded_on_the_day(
    summary: Summary, seeded_models: psycopg.Connection
) -> None:
    body = (await summary()).json()

    rows = companies(seeded_models)
    returns = [row[1] for row in rows if row[1] is not None]
    assert body["day"] == DAY.isoformat()
    assert rows
    assert body["breadth"] == pytest.approx(
        {
            "companies": len(rows),
            "advancing": sum(1 for value in returns if value > 0),
            "declining": sum(1 for value in returns if value < 0),
            "unchanged": sum(1 for value in returns if value == 0),
            "new_52w_highs": sum(1 for row in rows if row[3]),
            "new_52w_lows": sum(1 for row in rows if row[4]),
            "median_return_1d": median(returns),
        }
    )


@pytest.mark.parametrize(("side", "sign"), [("moved_up", 1), ("moved_down", -1)])
async def test_the_five_largest_moves_past_the_gate_are_listed_each_way(
    summary: Summary, seeded_models: psycopg.Connection, side: str, sign: int
) -> None:
    rows = (await summary()).json()[side]["rows"]

    expected = past_gate(ranked(seeded_models, sign))[:5]
    assert [row["isin"] for row in rows] == [row[0] for row in expected]
    assert len(rows) == 5
    assert all(row["symbol"] and row["display_name"] and row["close"] for row in rows)
    assert all(row["return_1d"] * sign > 0 for row in rows)


async def test_moves_below_the_gate_beyond_the_last_mover_are_named_and_counted(
    summary: Summary, seeded_models: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    moves = ranked(seeded_models, 1)
    last = past_gate(moves)[4][1]
    expected = below_gate_beyond(moves, last)
    assert len(expected) == 2
    monkeypatch.setattr(market_summary, "LARGEST_BELOW_GATE", 1)

    moved_up = (await summary()).json()["moved_up"]

    assert [move["isin"] for move in moved_up["below_gate"]] == expected[:1]
    assert moved_up["below_gate"][0]["display_name"]
    assert moved_up["below_gate"][0]["return_1d"] > last
    assert moved_up["more_below_gate"] == 1


@pytest.mark.parametrize(("side", "sign"), [("moved_up", 1), ("moved_down", -1)])
async def test_a_side_with_too_few_moves_lists_only_its_own_and_every_move_below_the_gate(
    summary: Summary,
    seeded_models: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    side: str,
    sign: int,
) -> None:
    monkeypatch.setattr(market_summary, "MOVERS", 40)
    monkeypatch.setattr(market_summary, "LARGEST_BELOW_GATE", 40)

    moved = (await summary()).json()[side]

    moves = ranked(seeded_models, sign)
    assert [row["isin"] for row in moved["rows"]] == [row[0] for row in past_gate(moves)]
    assert len(moved["rows"]) < 40
    assert [move["isin"] for move in moved["below_gate"]] == below_gate_beyond(moves, None)


async def test_a_mover_lists_the_unhandled_actions_its_return_runs_through(
    summary: Summary, seeded_models: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = (await summary()).json()
    assert not any(
        row["unhandled_actions"]
        for side in ("moved_up", "moved_down")
        for row in body[side]["rows"]
    )

    monkeypatch.setattr(market_summary, "RETURN_LOOKBACK_BARS", 63)
    rows = (await summary()).json()["moved_down"]["rows"]

    listed = 0
    for row in rows:
        bar = seeded_models.execute(
            BAR_BACK, (row["isin"], row["primary_venue"], DAY, 63)
        ).fetchone()
        assert bar is not None
        actions = seeded_models.execute(UNHANDLED, (row["isin"], bar[0], DAY))
        expected = [{"ex_date": ex.isoformat(), "purpose": text} for ex, text in actions]
        assert row["unhandled_actions"] == expected
        listed += len(expected)
    assert listed > 0


async def test_breadth_names_the_bhavcopies_and_movers_the_delivery_files_too(
    summary: Summary,
) -> None:
    body = (await summary()).json()

    bhavcopies = {"bse_bhavcopy_equity", "nse_bhavcopy_equity"}
    assert {source["source_id"] for source in body["breadth_sources"]} == bhavcopies
    assert {source["source_id"] for source in body["mover_sources"]} == bhavcopies | {
        "bse_delivery",
        "nse_delivery",
    }


async def test_before_the_first_publish_there_is_no_summary(
    start_api: StartApi, migrated_settings: ApiSettings, member_headers: dict[str, str]
) -> None:
    async with start_api(migrated_settings) as api:
        response = await api.get("/market/summary", headers=member_headers)

    empty = {"rows": [], "below_gate": [], "more_below_gate": 0}
    assert (response.status_code, response.json()) == (
        200,
        {
            "day": None,
            "breadth": None,
            "moved_up": empty,
            "moved_down": empty,
            "breadth_sources": [],
            "mover_sources": [],
        },
    )


async def test_the_summary_is_refused_without_a_session(summary: Summary) -> None:
    assert (await summary(signed_in=False)).status_code == 401
