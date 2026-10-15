"""Temporary passwords an admin hands over in person, which the holder replaces at first sign-in."""

import secrets
from datetime import timedelta
from functools import cache
from importlib.resources import files

from api.services.passwords import password_problem

# A temporary password stops opening its account this long after it was set.
TEMPORARY_PASSWORD_LIFETIME = timedelta(hours=24)
WORDS_PER_PASSWORD = 3
DIGITS = 4


@cache
def words() -> tuple[str, ...]:
    listed = files("api.services").joinpath("temporary_password_words.txt").read_text()
    return tuple(line for line in listed.splitlines() if line and not line.startswith("#"))


def temporary_password(*names: str) -> str:
    """Three words and four digits joined by hyphens, easy to read aloud, which the password rule
    admits for an account with these names."""
    while True:
        chosen = [secrets.choice(words()) for _ in range(WORDS_PER_PASSWORD)]
        password = "-".join([*chosen, f"{secrets.randbelow(10**DIGITS):0{DIGITS}d}"])
        if password_problem(password, *names) is None:
            return password
