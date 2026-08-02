"""Runtime configuration read from the environment."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(default="postgresql+psycopg://bitemporal@localhost:5432/bitemporal")
    data_env: str = Field(default="fixture", pattern="^(fixture|dev|full)$")

    @property
    def schema_name(self) -> str:
        return self.data_env
