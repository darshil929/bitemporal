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

    @property
    def schema_name(self) -> str:
        return self.data_env

    @property
    def async_database_url(self) -> str:
        _, _, rest = self.api_database_url.partition("://")
        return f"{ASYNC_DRIVER}://{rest}"
