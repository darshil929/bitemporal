from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer

from fixtures.loader import load_seed

# Matches the image the local stack runs, so tests exercise the same extensions.
POSTGRES_IMAGE = "timescale/timescaledb-ha:pg17"


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def seeded_postgres(postgres_dsn: str) -> str:
    load_seed(postgres_dsn)
    return postgres_dsn
