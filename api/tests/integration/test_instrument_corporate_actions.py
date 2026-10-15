"""An instrument's corporate actions up to the published day, read over the seed dataset."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest

from api.config import ApiSettings

pytestmark = pytest.mark.anyio

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]
Actions = Callable[..., Awaitable[httpx.Response]]


@pytest.fixture
def actions(
    start_api: StartApi, dataset_settings: ApiSettings, dataset_member_headers: dict[str, str]
) -> Actions:
    async def reading(isin: str, signed_in: bool = True) -> httpx.Response:
        async with start_api(dataset_settings) as api:
            headers = dataset_member_headers if signed_in else {}
            return await api.get(f"/instruments/{isin}/actions", headers=headers)

    return reading


async def listed(actions: Actions, isin: str) -> list[dict[str, Any]]:
    response = await actions(isin)
    assert response.status_code == 200
    return list(response.json())


async def test_actions_carry_their_terms_newest_first(actions: Actions) -> None:
    found = await listed(actions, "INE040A01034")
    on = {(action["ex_date"], action["action_type"]): action for action in found}

    assert [action["ex_date"] for action in found] == sorted(
        (action["ex_date"] for action in found), reverse=True
    )
    assert all(action["ex_date"] <= "2025-12-31" for action in found)
    bonus = on["2025-08-26", "bonus"]
    assert (bonus["terms"], bonus["adjustment_factor"], bonus["is_applied"]) == (
        "1 for 1",
        0.5,
        True,
    )
    assert (bonus["reported_by"], bonus["venues_differ"]) == ("both", False)
    assert on["2025-06-27", "dividend"]["dividend_amount"] == 22.0
    assert on["2025-07-25", "dividend"]["qualifier"] == "special"


async def test_an_unhandled_action_keeps_the_venues_text_and_applies_no_factor(
    actions: Actions,
) -> None:
    found = await listed(actions, "INE155A01022")

    unhandled = [
        (
            action["action_type"],
            action["reported_by"],
            action["purpose"],
            action["adjustment_factor"],
        )
        for action in found
        if action["ex_date"] == "2025-10-14"
    ]
    assert unhandled == [("unhandled", "both", "Spin Off", None)]


async def test_a_replaced_isin_lists_the_change_that_replaced_it(actions: Actions) -> None:
    found = await listed(actions, "INE296A01024")

    assert {action["action_type"] for action in found if action["ex_date"] == "2025-06-16"} == {
        "bonus",
        "split",
    }


async def test_an_unknown_isin_is_not_found(actions: Actions) -> None:
    response = await actions("INE999Z01019")

    assert response.status_code == 404
    assert response.json() == {"detail": {"reason": "instrument_not_found"}}


async def test_actions_are_refused_without_a_session(actions: Actions) -> None:
    assert (await actions("INE040A01034", signed_in=False)).status_code == 401
