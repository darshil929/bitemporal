"""Connections to the schema the active data environment names."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import ApiSettings


class Database:
    """A pool of connections, each reading the environment's schema before `public`."""

    def __init__(self, settings: ApiSettings) -> None:
        self.schema = settings.schema_name
        # Unqualified names resolve in the environment's schema; extension functions live in public.
        self.engine = create_async_engine(
            settings.async_database_url,
            pool_pre_ping=True,
            connect_args={
                "options": f"-csearch_path={settings.schema_name},public",
                "connect_timeout": settings.database_connect_timeout_seconds,
            },
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """A session inside one transaction, committed when the block ends, rolled back on error."""
        async with self._sessions() as session, session.begin():
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
