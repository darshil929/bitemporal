"""The interface the web client is built against: every path the API answers, what each accepts and
what each returns. The committed copy in api/openapi.json is the reviewed one, and a test fails while
the running application differs from it.
"""

import json
import sys

from api.main import create_app


def contract() -> str:
    """The interface in its committed form; the same interface always gives the same file."""
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    sys.stdout.write(contract())
