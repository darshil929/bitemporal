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
        "add_entry",
        "add_person",
        "add_watchlist",
        "admin_actions",
        "bootstrap_estimate",
        "change_account",
        "change_entry_venue",
        "change_password",
        "change_session_limits",
        "change_view",
        "create_first_admin",
        "data_status",
        "flow_request",
        "health",
        "instrument",
        "instrument_actions",
        "instrument_day",
        "instrument_prices",
        "market_day",
        "market_summary",
        "needs_attention",
        "people",
        "ready",
        "remove_alert",
        "remove_entry",
        "remove_view",
        "remove_watchlist",
        "rename_watchlist",
        "request_bootstrap",
        "request_sync",
        "reset_password",
        "run_history",
        "save_view",
        "saved_views",
        "screen",
        "search_instruments",
        "session",
        "session_limits",
        "set_alert",
        "setup",
        "sign_in",
        "sign_out",
        "sync_estimate",
        "watchlist_rows",
        "watchlists",
    ]
