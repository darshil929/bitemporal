import pytest

from check_commit_message import check


@pytest.mark.parametrize(
    "message",
    [
        "chore: add the repository toolchain",
        "feat(pipelines): add venue file ingestion",
        "fix(engine): harden indicator smoothing against short series",
    ],
)
def test_accepts_valid_messages(message: str) -> None:
    assert check(message) == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("feat(pipelines): Add Venue File Ingestion", "lowercase summary"),
        ("feat(pipelines): add venue file ingestion.", "lowercase summary"),
        ("added venue file ingestion", "lowercase summary"),
        ("feat(unknown): add venue file ingestion", "lowercase summary"),
        ("feat: " + "a" * 80, "the limit is 72"),
        ("feat: add venue file ingestion\n\nWith an explanatory body.", "single line"),
        ("", "empty"),
    ],
)
def test_rejects_invalid_messages(message: str, expected: str) -> None:
    errors = check(message)

    assert errors, f"expected {message!r} to be rejected"
    assert any(expected in error for error in errors)


def test_ignores_git_comment_lines() -> None:
    message = (
        "chore: add the repository toolchain\n# Please enter the commit message for your changes.\n"
    )

    assert check(message) == []
