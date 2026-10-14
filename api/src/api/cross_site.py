"""Refusal of requests that change something when another site sent them."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_same_origin(fetch_site: str | None, origin: str | None, app_origin: str | None) -> bool:
    """Browsers name the sending site in Sec-Fetch-Site; one too old to send it names the page's
    origin in Origin, which matches the application's own address only from its own pages."""
    if fetch_site is not None:
        return fetch_site == "same-origin"
    return app_origin is not None and origin == app_origin


async def refuse_cross_site(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    headers = request.headers
    if request.method not in SAFE_METHODS and not is_same_origin(
        headers.get("sec-fetch-site"), headers.get("origin"), request.app.state.settings.app_origin
    ):
        return JSONResponse(
            {"detail": "a request from another site may not change anything"},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return await call_next(request)
