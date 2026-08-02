"""Alembic environment targeting the schema named by the active data environment."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema

from pipelines.config.settings import DatabaseSettings
from pipelines.db.schema import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url(url: str) -> str:
    """Rewrite any Postgres URL to the driver migrations run on."""
    _, _, rest = url.partition("://")
    return f"postgresql+psycopg://{rest}"


def run_migrations_offline() -> None:
    settings = DatabaseSettings()
    context.configure(
        url=_sync_url(settings.database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = DatabaseSettings()
    schema = settings.schema_name
    # Unqualified objects are created in the leading schema. public trails it so that functions
    # and operators belonging to extensions resolve without qualification.
    engine = create_engine(
        _sync_url(settings.database_url),
        connect_args={"options": f"-csearch_path={schema},public"},
    )

    try:
        with engine.connect() as connection:
            connection.execute(CreateSchema(schema, if_not_exists=True))
            connection.commit()

            # Placement comes from search_path. Naming the schema explicitly would stop
            # autogenerate recognising the version table as its own.
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
