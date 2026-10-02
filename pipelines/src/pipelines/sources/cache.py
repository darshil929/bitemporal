"""Storage for raw source responses, keyed by source and partition."""

import json
import logging
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

NOTICED = re.compile(r"\d{8}")


class DiskCache:
    """Holds each response under its source and partition.

    Entries are never evicted, and a file a venue corrects is held beside the copy it corrects,
    named for the day the change was noticed. Re-reading a file costs a request against a rate
    limited endpoint, so the validators it was served with are held beside it.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, source_id: str, partition_key: str, suffix: str) -> Path:
        return self.root / source_id / f"{partition_key}{suffix}"

    def read(self, source_id: str, partition_key: str, suffix: str) -> bytes | None:
        path = self.path_for(source_id, partition_key, suffix)
        if not path.is_file():
            return None
        logger.debug(
            "source cache hit", extra={"source_id": source_id, "partition_key": partition_key}
        )
        return path.read_bytes()

    def write(self, source_id: str, partition_key: str, suffix: str, payload: bytes) -> Path:
        path = self.path_for(source_id, partition_key, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        logger.info(
            "source response cached",
            extra={
                "source_id": source_id,
                "partition_key": partition_key,
                "bytes": len(payload),
            },
        )
        return path

    def latest(self, source_id: str, partition_key: str, suffix: str) -> bytes | None:
        """The most recent version held of a partition, the first copy where none followed it."""
        later = self.versions(source_id, partition_key, suffix)
        if later:
            return later[-1][1]
        return self.read(source_id, partition_key, suffix)

    def versions(self, source_id: str, partition_key: str, suffix: str) -> list[tuple[date, bytes]]:
        """Each corrected copy held of a partition with the day it was noticed, the oldest first."""
        found = []
        for path in sorted(self.root.joinpath(source_id).glob(f"{partition_key}.as-of-*{suffix}")):
            noticed = path.name.removeprefix(f"{partition_key}.as-of-").removesuffix(suffix)
            if NOTICED.fullmatch(noticed):
                found.append((date(int(noticed[:4]), int(noticed[4:6]), int(noticed[6:])), path))
        return [(noticed, path.read_bytes()) for noticed, path in found]

    def write_version(
        self, source_id: str, partition_key: str, suffix: str, noticed_on: date, payload: bytes
    ) -> Path:
        return self.write(source_id, f"{partition_key}.as-of-{noticed_on:%Y%m%d}", suffix, payload)

    def read_validators(self, source_id: str, partition_key: str, suffix: str) -> dict[str, str]:
        path = self._validators_path(source_id, partition_key, suffix)
        return dict(json.loads(path.read_text())) if path.is_file() else {}

    def write_validators(
        self, source_id: str, partition_key: str, suffix: str, validators: Mapping[str, str]
    ) -> None:
        if validators:
            path = self._validators_path(source_id, partition_key, suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(validators)))

    def _validators_path(self, source_id: str, partition_key: str, suffix: str) -> Path:
        return self.path_for(source_id, partition_key, f"{suffix}.validators.json")
