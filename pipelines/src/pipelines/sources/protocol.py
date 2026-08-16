"""The contract every external source adapter implements."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class MarketDataProvider(Protocol):
    """Three stages, separable so that only the first performs input or output.

    `fetch` returns the bytes a venue published for one partition, reading from the disk cache
    when they are already present. `parse` turns those bytes into validated records and holds no
    state, making it testable against a recorded fixture. `normalize` maps records onto the
    canonical schema and resolves each row to an ISIN.
    """

    source_id: str

    def fetch(self, partition: date) -> bytes: ...

    def parse(self, payload: bytes, schema_version: str) -> Sequence[BaseModel]: ...

    def normalize(self, records: Sequence[BaseModel]) -> Sequence[BaseModel]: ...
