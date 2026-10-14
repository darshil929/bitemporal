"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from api.config import ApiSettings
from api.db.database import Database
from api.log_format import configure_logging
from api.routers import auth, health, sessions


def operation_id(route: APIRoute) -> str:
    """The name the web client calls an operation by: its endpoint's, `ready` for `/ready`."""
    return route.name


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """The API service, holding its database connections from start to stop."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The environment supplies the API's database URL.
        active = settings or ApiSettings()  # type: ignore[call-arg]
        configure_logging(active.log_level)
        app.state.settings = active
        app.state.database = Database(active)
        try:
            yield
        finally:
            await app.state.database.close()

    app = FastAPI(
        title="Bitemporal API",
        version="0.0.0",
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(sessions.router)
    return app


app = create_app()
