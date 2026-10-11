from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from api.services.readiness import EXPECTED_REVISION

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "pipelines" / "alembic.ini"


def test_the_api_expects_the_latest_migration() -> None:
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()

    assert EXPECTED_REVISION == head
