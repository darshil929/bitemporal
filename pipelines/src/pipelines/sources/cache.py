"""Storage for raw source responses, keyed by source and partition."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DiskCache:
    """Holds each response under its source and partition.

    Entries are never evicted. An exchange file for a past trading day does not change, and
    re-reading one costs a request against a rate limited endpoint.
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
