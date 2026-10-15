import base64
import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from api.config import ApiSettings
from api.main import create_app
from fixtures.database import MIGRATION_SCHEMA, SEED_SCHEMA

UNREACHABLE_DSN = "postgresql://nobody:nothing@127.0.0.1:1/nowhere"

API_ROLE = "bitemporal_api"
API_ROLE_PASSWORD = "api-tests"

SESSION_COOKIE = "__Host-bitemporal_session"
NEW_ACCOUNT = (
    "insert into app_user (username, display_name, role, password_hash)"
    " values (%s, %s, %s, 'unused') returning id"
)
NEW_SESSION = "insert into app_session (owner_id, token_hash) values (%s, %s)"

StartApi = Callable[[ApiSettings], AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def settings_for(dsn: str, schema: str) -> ApiSettings:
    """Settings naming the database outright, so no `.env` or variable can redirect them."""
    return ApiSettings(api_database_url=dsn, data_env=schema, _env_file=None)  # type: ignore[call-arg]


def as_api_role(dsn: str) -> str:
    """The test database's address for the API's role, which the migrations create unpassworded."""
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("alter role {} password {}").format(
                sql.Identifier(API_ROLE), sql.Literal(API_ROLE_PASSWORD)
            )
        )
    address = make_url(dsn).set(username=API_ROLE, password=API_ROLE_PASSWORD)
    return address.render_as_string(hide_password=False)


@pytest.fixture
def migrated_settings(migrated: Config, postgres_dsn: str) -> ApiSettings:
    """The API pointed at a schema migrated to head and holding no rows, as its own role."""
    return settings_for(as_api_role(postgres_dsn), MIGRATION_SCHEMA)


@pytest.fixture
def owner_settings(migrated: Config, postgres_dsn: str) -> ApiSettings:
    """The API pointed at the same schema as the owner of its tables, a superuser."""
    return settings_for(postgres_dsn, MIGRATION_SCHEMA)


@pytest.fixture
def dataset_settings(seeded_models: psycopg.Connection, seeded_postgres: str) -> ApiSettings:
    """The API pointed at the seed dataset, its models built and its daily features stored."""
    return settings_for(as_api_role(seeded_postgres), SEED_SCHEMA)


def account_session(dsn: str, schema: str, username: str, role: str = "member") -> dict[str, str]:
    """Request headers carrying a running session of a new account, written by the tables' owner."""
    token = secrets.token_bytes(32)
    with psycopg.connect(dsn, options=f"-csearch_path={schema},public", autocommit=True) as owner:
        account = owner.execute(NEW_ACCOUNT, (username, username.title(), role)).fetchone()
        assert account is not None
        owner.execute(NEW_SESSION, (account[0], hashlib.sha256(token).digest()))
    cookie = base64.urlsafe_b64encode(token).rstrip(b"=").decode()
    return {"Cookie": f"{SESSION_COOKIE}={cookie}"}


@pytest.fixture
def member_headers(migrated: Config, postgres_dsn: str) -> dict[str, str]:
    """A member signed in to the schema `migrated_settings` serves."""
    return account_session(postgres_dsn, MIGRATION_SCHEMA, "reader")


@pytest.fixture
def admin_headers(migrated: Config, postgres_dsn: str) -> dict[str, str]:
    """An admin signed in to the schema `migrated_settings` serves."""
    return account_session(postgres_dsn, MIGRATION_SCHEMA, "meera", role="admin")


@pytest.fixture(scope="session")
def dataset_member_headers(
    seeded_models: psycopg.Connection, seeded_postgres: str
) -> dict[str, str]:
    """A member signed in to the seed dataset, written once for the whole test session."""
    return account_session(seeded_postgres, SEED_SCHEMA, "dataset-reader")


@pytest.fixture
def unreachable_settings() -> ApiSettings:
    return settings_for(UNREACHABLE_DSN, MIGRATION_SCHEMA)


@asynccontextmanager
async def running_api(settings: ApiSettings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            yield client


@pytest.fixture
def start_api() -> StartApi:
    """Requests to a running copy of the API, started with the given settings."""
    return running_api
