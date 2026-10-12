"""The API's log, each record carrying its identifiers as fields an operator can search on."""

import json
import logging
from datetime import UTC, datetime

# Python's logging keeps the fields passed in `extra` as attributes beside these, its own.
RECORD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(
            (name, value) for name, value in vars(record).items() if name not in RECORD_ATTRIBUTES
        )
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    """The API's own records from `level` up, on standard error, where a container's log is read."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("api")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
