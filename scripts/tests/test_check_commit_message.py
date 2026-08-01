import pytest

from check_commit_message import check


@pytest.mark.parametrize(
    "message",
    [
        "chore: add uv workspace with pipelines and api skeletons",
        "feat(pipelines): add bse bhavcopy adapter with disk cache",
        "fix(engine): correct wilder smoothing seed",
    ],
)
def test_accepts_valid_messages(message: str) -> None:
    assert check(message) == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("feat(pipelines): Add BSE bhavcopy adapter", "lowercase summary"),
        ("feat(pipelines): add adapter.", "lowercase summary"),
        ("added a bhavcopy adapter", "lowercase summary"),
        ("feat(unknown): add something", "lowercase summary"),
        ("feat: " + "a" * 80, "the limit is 72"),
        ("feat: add adapter\n\nWith an explanatory body.", "single line"),
        ("", "empty"),
    ],
)
def test_rejects_invalid_messages(message: str, expected: str) -> None:
    errors = check(message)

    assert errors, f"expected {message!r} to be rejected"
    assert any(expected in error for error in errors)


def test_ignores_git_comment_lines() -> None:
    message = "chore: add makefile\n# Please enter the commit message for your changes.\n"

    assert check(message) == []
