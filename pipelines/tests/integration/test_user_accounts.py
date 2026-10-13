"""Each person's account, sessions and settings, as the API's role reaches them for that person."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import psycopg
import pytest
from alembic.config import Config

from fixtures.database import MIGRATION_SCHEMA

RAVI, ASHA, MEERA = 1, 2, 3


def token_hash(person: int) -> bytes:
    return hashlib.sha256(f"token of {person}".encode()).digest()


@pytest.fixture
def people(migrated: Config, postgres_dsn: str) -> str:
    """Ravi, an admin, and Asha and Meera, members, each signed in once with a setting."""
    with psycopg.connect(postgres_dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as owner:
        for username, role in (("ravi", "admin"), ("asha", "member"), ("meera", "member")):
            owner.execute(
                "insert into app_user (username, display_name, role, password_hash)"
                " values (%s, %s, %s, %s)",
                (username, username.title(), role, f"hash of {username}"),
            )
        for person in (RAVI, ASHA, MEERA):
            owner.execute(
                "insert into app_session (owner_id, token_hash) values (%s, %s)",
                (person, token_hash(person)),
            )
            owner.execute("insert into user_setting (owner_id) values (%s)", (person,))
    return postgres_dsn


@contextmanager
def signed_in(dsn: str, person: int | None) -> Iterator[psycopg.Connection]:
    """The API's role in a transaction acting for `person`, or for nobody before sign-in."""
    with psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public") as connection:
        connection.execute("set role bitemporal_api")
        if person is not None:
            connection.execute("select set_config('app.user_id', %s, true)", (str(person),))
        yield connection


def ids(connection: psycopg.Connection, query: str) -> list[int]:
    return [row[0] for row in connection.execute(query).fetchall()]


@pytest.mark.parametrize(
    ("person", "accounts", "sessions"),
    [(None, [], []), (ASHA, [ASHA], [ASHA]), (RAVI, [RAVI, ASHA, MEERA], [RAVI, ASHA, MEERA])],
)
def test_a_person_sees_their_own_account_and_an_admin_every_one(
    people: str, person: int | None, accounts: list[int], sessions: list[int]
) -> None:
    with signed_in(people, person) as api:
        assert ids(api, "select id from app_user order by id") == accounts
        assert ids(api, "select owner_id from app_session order by owner_id") == sessions


@pytest.mark.parametrize("person", [ASHA, RAVI])
def test_settings_are_their_owners_alone(people: str, person: int) -> None:
    with signed_in(people, person) as api:
        assert ids(api, "select owner_id from user_setting") == [person]
        updated = api.execute(
            "update user_setting set theme = 'dark' where owner_id = %s", (MEERA,)
        )
        assert updated.rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("insert into user_setting (owner_id) values (%s)", (MEERA,))


@pytest.mark.parametrize(
    "statement",
    [
        "select password_hash from app_user",
        "select token_hash from app_session",
        "delete from app_session",
        "delete from user_setting",
        "delete from app_user",
    ],
)
def test_the_role_reads_no_secret_and_deletes_nothing(people: str, statement: str) -> None:
    with signed_in(people, RAVI) as api, pytest.raises(psycopg.errors.InsufficientPrivilege):
        api.execute(statement)


def test_sign_in_reads_an_account_and_records_a_failure_before_anyone_is_signed_in(
    people: str,
) -> None:
    pause = datetime(2026, 10, 13, 12, tzinfo=UTC)
    with signed_in(people, None) as api:
        found = api.execute("select id, password_hash from sign_in_candidate('Asha')").fetchone()
        failures = api.execute("select record_failed_sign_in(%s, %s)", (ASHA, pause)).fetchone()
        session = api.execute(
            "select owner_id from session_for_token(%s)", (token_hash(MEERA),)
        ).fetchone()

    assert found == (ASHA, "hash of asha")
    assert failures == (1,)
    assert session == (MEERA,)


def test_only_an_admin_adds_an_account(people: str) -> None:
    added = "insert into app_user (username, display_name, role, password_hash) values (%s, %s, 'member', 'h')"
    with signed_in(people, ASHA) as api, pytest.raises(psycopg.errors.InsufficientPrivilege):
        api.execute(added, ("kiran", "Kiran"))
    with signed_in(people, RAVI) as api:
        api.execute(added, ("kiran", "Kiran"))


def test_a_member_renames_themselves_and_changes_nothing_an_admin_holds(people: str) -> None:
    with signed_in(people, ASHA) as api:
        api.execute("update app_user set display_name = 'Asha R' where id = %s", (ASHA,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("update app_user set role = 'admin' where id = %s", (ASHA,))


def test_the_last_enabled_admin_stays_one(people: str) -> None:
    with signed_in(people, RAVI) as api, pytest.raises(psycopg.errors.RestrictViolation):
        api.execute("update app_user set disabled_at = now() where id = %s", (RAVI,))
    with signed_in(people, RAVI) as api:
        api.execute("update app_user set role = 'admin' where id = %s", (ASHA,))
        api.execute("update app_user set role = 'member' where id = %s", (RAVI,))


def test_an_admin_ends_another_persons_session_and_a_member_does_not(people: str) -> None:
    ending = (
        "update app_session set ended_at = now(), ended_reason = 'disabled' where owner_id = %s"
    )
    with signed_in(people, ASHA) as api:
        assert api.execute(ending, (MEERA,)).rowcount == 0
    with signed_in(people, RAVI) as api:
        assert api.execute(ending, (MEERA,)).rowcount == 1


def test_a_person_starts_sessions_for_themselves_alone(people: str) -> None:
    starting = "insert into app_session (owner_id, token_hash) values (%s, %s)"
    with signed_in(people, ASHA) as api:
        api.execute(starting, (ASHA, hashlib.sha256(b"second device").digest()))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute(starting, (MEERA, hashlib.sha256(b"not hers").digest()))


def test_session_limits_are_read_by_anyone_and_changed_by_an_admin(people: str) -> None:
    changing = "update app_setting set session_idle_minutes = 60"
    with signed_in(people, None) as api:
        assert api.execute(
            "select session_idle_minutes, session_max_hours from app_setting"
        ).fetchone() == (120, 12)
    with signed_in(people, ASHA) as api:
        assert api.execute(changing).rowcount == 0
    with signed_in(people, RAVI) as api:
        assert api.execute(changing).rowcount == 1


def test_the_first_admin_is_created_once(migrated: Config, postgres_dsn: str) -> None:
    creating = "select create_first_admin(%s, %s, %s)"
    with signed_in(postgres_dsn, None) as api:
        assert api.execute(creating, ("Ravi", "Ravi", "h")).fetchone() == (1,)
        with pytest.raises(psycopg.errors.RaiseException):
            api.execute(creating, ("asha", "Asha", "h"))
