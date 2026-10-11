"""The API's log records as one JSON object a line, carrying the fields passed in `extra`."""

import json
import logging
from datetime import UTC, datetime

# Attributes every record carries; any other attribute on a record came from `extra`.
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
    """Write the `api` loggers' records to standard error as JSON lines from `level` up."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("api")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
