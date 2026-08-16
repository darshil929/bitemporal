"""Loads the committed fixture dataset into the database named by DATABASE_URL."""

import logging
import sys
from pathlib import Path

logger = logging.getLogger("seed")

FIXTURES = Path(__file__).resolve().parents[1] / "pipelines" / "tests"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # The loader lives beside the data it loads, which pytest puts on the path and this does not.
    sys.path.insert(0, str(FIXTURES))
    from fixtures.loader import SEED_SCHEMA, load_seed
    from pipelines.config.settings import DatabaseSettings

    load_seed(DatabaseSettings().database_url)
    logger.info("fixture seed loaded", extra={"schema": SEED_SCHEMA})
    return 0


if __name__ == "__main__":
    sys.exit(main())
