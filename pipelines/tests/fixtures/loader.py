"""Materialize the committed seed dataset into a Postgres database."""

from pathlib import Path

import psycopg

SEED_DIR = Path(__file__).parent / "seed"

# Ordered so foreign keys resolve.
SEED_TABLES = ("instrument", "listing", "price_daily", "corporate_action")


def load_seed(dsn: str, seed_dir: Path = SEED_DIR) -> None:
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute((seed_dir / "schema.sql").read_text(encoding="utf-8"))

            for table in SEED_TABLES:
                csv_path = seed_dir / f"{table}.csv"
                columns = csv_path.read_text(encoding="utf-8").splitlines()[0]
                copy = f"copy fixture.{table} ({columns}) from stdin with (format csv, header true)"

                with cursor.copy(copy) as copier:
                    copier.write(csv_path.read_bytes())

        connection.commit()
