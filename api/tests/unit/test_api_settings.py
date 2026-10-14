import pytest
from pydantic import ValidationError

from api.config import ApiSettings


def settings(**values: str) -> ApiSettings:
    return ApiSettings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://bitemporal:secret@localhost:5433/bitemporal",
        "postgresql+psycopg://bitemporal:secret@localhost:5433/bitemporal",
        "postgresql+asyncpg://bitemporal:secret@localhost:5433/bitemporal",
    ],
)
def test_every_postgres_url_is_served_through_psycopg(url: str) -> None:
    assert (
        settings(api_database_url=url).async_database_url
        == "postgresql+psycopg://bitemporal:secret@localhost:5433/bitemporal"
    )


ADDRESS = "postgresql://bitemporal_api:secret@localhost:5433/bitemporal"


def test_the_data_environment_names_the_schema() -> None:
    assert settings(api_database_url=ADDRESS, data_env="full").schema_name == "full"


def test_an_unknown_data_environment_is_refused() -> None:
    with pytest.raises(ValidationError):
        settings(api_database_url=ADDRESS, data_env="staging")


def test_the_environment_supplies_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_DATABASE_URL", "postgresql://bitemporal_api@db:5432/bitemporal")
    monkeypatch.setenv("DATA_ENV", "dev")

    read = settings()

    assert read.async_database_url == "postgresql+psycopg://bitemporal_api@db:5432/bitemporal"
    assert read.schema_name == "dev"


def test_the_address_the_pipelines_connect_through_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without its own address the API does not start, rather than connect as the owner."""
    monkeypatch.delenv("API_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://bitemporal@db:5432/bitemporal")

    with pytest.raises(ValidationError):
        settings()
