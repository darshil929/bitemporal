import json
import logging
import sys

from api.log_format import JsonFormatter


def formatted(record: logging.LogRecord) -> dict[str, object]:
    parsed: dict[str, object] = json.loads(JsonFormatter().format(record))
    return parsed


def test_a_record_carries_its_extra_fields() -> None:
    record = logging.makeLogRecord(
        {
            "name": "api.services.readiness",
            "levelname": "WARNING",
            "msg": "database not ready",
            "schema": "full",
            "revision": "0015",
        }
    )

    entry = formatted(record)

    assert entry["level"] == "WARNING"
    assert entry["logger"] == "api.services.readiness"
    assert entry["message"] == "database not ready"
    assert entry["schema"] == "full"
    assert entry["revision"] == "0015"
    assert "args" not in entry


def test_a_record_with_an_exception_carries_its_traceback() -> None:
    try:
        raise ValueError("unreadable")
    except ValueError:
        record = logging.getLogger("api").makeRecord(
            "api", logging.ERROR, __file__, 1, "request failed", (), sys.exc_info()
        )

    assert "ValueError: unreadable" in str(formatted(record)["exception"])
