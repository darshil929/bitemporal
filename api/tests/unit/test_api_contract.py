import json
from pathlib import Path

from api.contract import contract

COMMITTED_CONTRACT = Path(__file__).resolve().parents[2] / "openapi.json"


def test_the_application_serves_the_committed_contract() -> None:
    assert contract() == COMMITTED_CONTRACT.read_text(), (
        "the API's OpenAPI document differs from api/openapi.json; review the change and write it"
        " with make openapi"
    )


def test_each_operation_carries_its_endpoint_name() -> None:
    paths = json.loads(contract())["paths"]
    names = [operation["operationId"] for path in paths.values() for operation in path.values()]

    assert len(names) == len(set(names))
    assert sorted(names) == [
        "add_person",
        "admin_actions",
        "change_account",
        "change_password",
        "change_session_limits",
        "create_first_admin",
        "health",
        "instrument",
        "instrument_actions",
        "instrument_day",
        "instrument_prices",
        "market_day",
        "people",
        "ready",
        "reset_password",
        "search_instruments",
        "session",
        "session_limits",
        "setup",
        "sign_in",
        "sign_out",
    ]
