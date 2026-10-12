"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from api.config import ApiSettings
from api.db.database import Database
from api.log_format import configure_logging
from api.routers import health


def operation_id(route: APIRoute) -> str:
    """Each operation is named after its endpoint function, a name unique across the routers."""
    return route.name


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """The application, reading `settings`, or the environment when none are given, as it starts."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = settings or ApiSettings()
        configure_logging(active.log_level)
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
    return app


app = create_app()
