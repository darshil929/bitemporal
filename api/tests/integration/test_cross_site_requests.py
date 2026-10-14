"""Refusal of requests that change something when another site sent them."""

import httpx
import pytest
from fastapi import APIRouter

from api.config import ApiSettings
from api.main import create_app

pytestmark = pytest.mark.anyio

ORIGIN = "https://bitemporal.lan"


async def answer(settings: ApiSettings, method: str, headers: dict[str, str]) -> int:
    """The status of a request to a route that changes nothing but accepts any method."""
    app = create_app(settings.model_copy(update={"app_origin": ORIGIN}))
    changes = APIRouter()

    @changes.api_route("/changes", methods=["GET", "POST", "DELETE"], status_code=204)
    def change() -> None:
        return None

    app.include_router(changes)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as api:
            return (await api.request(method, "/changes", headers=headers)).status_code


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Sec-Fetch-Site": "same-origin"}, 204),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Sec-Fetch-Site": "same-site"}, 403),
        ({"Sec-Fetch-Site": "cross-site", "Origin": ORIGIN}, 403),
        ({"Origin": ORIGIN}, 204),
        ({"Origin": "https://elsewhere.example"}, 403),
        ({}, 403),
    ],
)
@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_a_change_from_another_site_is_refused(
    unreachable_settings: ApiSettings, method: str, headers: dict[str, str], status: int
) -> None:
    assert await answer(unreachable_settings, method, headers) == status


async def test_a_read_from_another_site_is_answered(unreachable_settings: ApiSettings) -> None:
    assert await answer(unreachable_settings, "GET", {"Sec-Fetch-Site": "cross-site"}) == 204


async def test_without_the_application_s_address_only_sec_fetch_site_admits_a_change(
    unreachable_settings: ApiSettings,
) -> None:
    app = create_app(unreachable_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as api:
            refused = await api.post("/ready", headers={"Origin": ORIGIN})

    assert refused.status_code == 403
