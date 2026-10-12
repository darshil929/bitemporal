"""The API's OpenAPI document, written as the committed contract the web client is generated from.

python -m api.contract > api/openapi.json
"""

import json
import sys

from api.main import create_app


def contract() -> str:
    """The OpenAPI document with sorted keys and a final newline, so a change reads as a diff."""
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    sys.stdout.write(contract())
