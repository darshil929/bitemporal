"""Password hashes: Argon2id at the library's settings, above OWASP's minimum for it."""

import secrets
from functools import cache
from typing import Literal

import anyio
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

PASSWORDS = PasswordHash((Argon2Hasher(),))

# Length is the rule, with no rule on the kinds of character; a password may not contain the
# account's own names or the application's.
SHORTEST_PASSWORD = 15
LONGEST_PASSWORD = 128
APPLICATION_NAME = "bitemporal"

PasswordProblem = Literal["too_short", "too_long", "contains_a_name"]


def password_problem(password: str, *names: str) -> PasswordProblem | None:
    """What makes the password unusable for an account with these names, or None."""
    if len(password) < SHORTEST_PASSWORD:
        return "too_short"
    if len(password) > LONGEST_PASSWORD:
        return "too_long"
    lowered = password.casefold()
    if any(name.casefold() in lowered for name in (*names, APPLICATION_NAME) if name):
        return "contains_a_name"
    return None


def hash_password(password: str) -> str:
    return PASSWORDS.hash(password)


@cache
def unmatched_hash() -> str:
    """A hash no typed password matches, checked when no account has the username typed, so the
    answer takes as long as it does for an account that exists."""
    return PASSWORDS.hash(secrets.token_urlsafe(32))


async def verify(password: str, stored: str) -> tuple[bool, str | None]:
    """Whether the password matches, and its hash again where the stored one used weaker settings.

    Hashing holds a thread for tens of milliseconds, so it runs off the event loop.
    """
    return await anyio.to_thread.run_sync(PASSWORDS.verify_and_update, password, stored)
