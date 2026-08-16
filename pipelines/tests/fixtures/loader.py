"""Materialize the committed seed dataset into a Postgres database.

The schema comes from the migrations rather than a copy kept beside the data, so the fixture
exercises the tables the application actually uses.

`listing_date` in the seed is the first day an instrument appears in the recorded window, not the
day it listed. A test asserting a real listing date would be asserting the window.

Corporate actions carry the whole history the venue reports, reaching back before the price window,
because adjustment needs every action ahead of a bar. Their `as_of_date` is the date they were
collected rather than announced, which the venue does not publish.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config

SEED_DIR = Path(__file__).parent / "seed"
PIPELINES_ROOT = Path(__file__).resolve().parents[2]
SEED_SCHEMA = "fixture"

# Ordered so foreign keys resolve.
SEED_TABLES = ("instrument_master", "listing", "price_daily", "corporate_action")


@contextmanager
def _pointed_at(dsn: str) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "DATA_ENV")}
    os.environ["DATABASE_URL"] = dsn
    os.environ["DATA_ENV"] = SEED_SCHEMA
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _psycopg_dsn(url: str) -> str:
    """Strip the SQLAlchemy driver, which psycopg does not accept."""
    _, _, rest = url.partition("://")
    return f"postgresql://{rest}"


def load_seed(dsn: str, seed_dir: Path = SEED_DIR) -> None:
    with _pointed_at(dsn):
        command.upgrade(Config(PIPELINES_ROOT / "alembic.ini"), "head")

    with psycopg.connect(
        _psycopg_dsn(dsn), options=f"-csearch_path={SEED_SCHEMA},public"
    ) as connection:
        with connection.cursor() as cursor:
            for table in SEED_TABLES:
                csv_path = seed_dir / f"{table}.csv"
                columns = csv_path.read_text(encoding="utf-8").splitlines()[0]
                copy = (
                    f"copy {SEED_SCHEMA}.{table} ({columns})"
                    " from stdin with (format csv, header true)"
                )

                with cursor.copy(copy) as copier:
                    copier.write(csv_path.read_bytes())

        connection.commit()
