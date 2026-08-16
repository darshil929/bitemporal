"""Runtime configuration read from the environment."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(default="postgresql+psycopg://bitemporal@localhost:5432/bitemporal")
    data_env: str = Field(default="fixture", pattern="^(fixture|dev|full)$")

    @property
    def schema_name(self) -> str:
        return self.data_env


class SourceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    source_cache_dir: Path = Field(default=Path("~/bitemporal/cache"))
    source_user_agent: str = Field(default="bitemporal (personal research)")
    source_request_delay_seconds: float = Field(default=2.0, gt=0)

    @field_validator("source_cache_dir")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        return value.expanduser()
