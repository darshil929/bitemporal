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
        settings(database_url=url).async_database_url
        == "postgresql+psycopg://bitemporal:secret@localhost:5433/bitemporal"
    )


def test_the_data_environment_names_the_schema() -> None:
    assert settings(data_env="full").schema_name == "full"


def test_an_unknown_data_environment_is_refused() -> None:
    with pytest.raises(ValidationError):
        settings(data_env="staging")


def test_the_environment_supplies_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://reader@db:5432/bitemporal")
    monkeypatch.setenv("DATA_ENV", "dev")

    read = settings()

    assert read.async_database_url == "postgresql+psycopg://reader@db:5432/bitemporal"
    assert read.schema_name == "dev"
