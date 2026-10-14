"""Runtime configuration of the API, read from the environment."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The API connects as a role of its own, which owns nothing and which row security binds, through
# API_DATABASE_URL; the migrations, dbt and the flows connect through DATABASE_URL. Whichever
# driver the URL names, the API connects through psycopg.
ASYNC_DRIVER = "postgresql+psycopg"


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_database_url: str
    data_env: str = Field(default="fixture", pattern="^(fixture|dev|full)$")
    database_connect_timeout_seconds: int = Field(default=5, gt=0)
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    # Served over HTTPS the session cookie is Secure and takes the __Host- prefix, which binds it to
    # the host that set it; a deployment served over plain HTTP on its own network turns this off.
    session_cookie_secure: bool = True
    # The address the application's pages are served from, which a browser too old to send
    # Sec-Fetch-Site names in Origin; without it such a browser changes nothing.
    app_origin: str | None = None

    @property
    def schema_name(self) -> str:
        return self.data_env

    @property
    def session_cookie_name(self) -> str:
        return "__Host-bitemporal_session" if self.session_cookie_secure else "bitemporal_session"

    @property
    def async_database_url(self) -> str:
        _, _, rest = self.api_database_url.partition("://")
        return f"{ASYNC_DRIVER}://{rest}"
