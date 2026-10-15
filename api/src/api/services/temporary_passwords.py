"""Temporary passwords an admin hands over in person, which the holder replaces at first sign-in."""

import secrets
import string
from datetime import timedelta

from api.services.passwords import password_problem

# A temporary password stops opening its account this long after it was set.
TEMPORARY_PASSWORD_LIFETIME = timedelta(hours=24)
TEMPORARY_PASSWORD_LENGTH = 16
CHARACTERS = string.ascii_letters + string.digits


def temporary_password(*names: str) -> str:
    """Random letters and digits which the password rule admits for an account with these names."""
    while True:
        password = "".join(secrets.choice(CHARACTERS) for _ in range(TEMPORARY_PASSWORD_LENGTH))
        if password_problem(password, *names) is None:
            return password
