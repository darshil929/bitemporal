"""Validate a commit message against the repository's commit conventions."""

import re
import sys
from pathlib import Path

TYPES = ("build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor", "revert", "test")
SCOPES = ("api", "docs", "engine", "infra", "pipelines", "web")

MAX_LENGTH = 72

SUBJECT = re.compile(
    rf"^(?:{'|'.join(TYPES)})(?:\((?:{'|'.join(SCOPES)})\))?: [a-z0-9][^A-Z]*[^.\s]$"
)


def check(message: str) -> list[str]:
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    body = [line for line in lines[1:] if line.strip()]
    subject = lines[0].strip() if lines else ""

    errors: list[str] = []

    if not subject:
        return ["commit message is empty"]

    if body:
        errors.append("commit message must be a single line with no body")

    if len(subject) > MAX_LENGTH:
        errors.append(f"subject is {len(subject)} characters, the limit is {MAX_LENGTH}")

    if not SUBJECT.match(subject):
        errors.append(
            "subject must read '<type>(<scope>): <lowercase summary>' with no trailing period, "
            f"where type is one of {', '.join(TYPES)} and scope is one of {', '.join(SCOPES)}"
        )

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check_commit_message.py <path-to-commit-message-file>", file=sys.stderr)
        return 2

    errors = check(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not errors:
        return 0

    for error in errors:
        print(f"commit message: {error}", file=sys.stderr)
    print("\nexample: feat(pipelines): add bse bhavcopy adapter with disk cache", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
