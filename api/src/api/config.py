"""Runtime configuration of the API, read from the environment."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# psycopg serves every connection, whichever driver a Postgres URL names.
ASYNC_DRIVER = "postgresql+psycopg"


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(default="postgresql+psycopg://bitemporal@localhost:5432/bitemporal")
    data_env: str = Field(default="fixture", pattern="^(fixture|dev|full)$")
    database_connect_timeout_seconds: int = Field(default=5, gt=0)
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    @property
    def schema_name(self) -> str:
        return self.data_env

    @property
    def async_database_url(self) -> str:
        _, _, rest = self.database_url.partition("://")
        return f"{ASYNC_DRIVER}://{rest}"
