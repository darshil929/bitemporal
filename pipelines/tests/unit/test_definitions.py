from dagster import Definitions

from pipelines.definitions import defs


def test_definitions_loads() -> None:
    assert isinstance(defs, Definitions)
