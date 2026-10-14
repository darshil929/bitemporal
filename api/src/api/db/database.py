"""Connections to the schema the active data environment names."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import ApiSettings

# The person a transaction acts for, which row security compares each row's owner with. Set for the
# transaction alone, so it ends with it.
ACTING_FOR = text("select set_config('app.user_id', :user, true)")


class Database:
    """The API's connections to the data of the environment it serves: `fixture`, `dev` or `full`."""

    def __init__(self, settings: ApiSettings) -> None:
        self.schema = settings.schema_name
        # Each environment's tables are a schema of their own; the extensions' functions live in public.
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
    async def transaction(self, user_id: int | None = None) -> AsyncIterator[AsyncSession]:
        """One unit of work: everything it writes is kept together, or nothing is.

        Acting for `user_id`, it reaches that person's own rows; acting for no one, it reaches no
        person's. A pooled connection carries no one into its next transaction.
        """
        async with self._sessions() as session, session.begin():
            if user_id is not None:
                await session.execute(ACTING_FOR, {"user": str(user_id)})
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
