"""Asking again for a file already held, and holding a changed one beside the copy it changes."""

from collections.abc import Callable, Mapping
from datetime import date

from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Answer


def unchanged(payload: bytes) -> bytes:
    return payload


def recheck(
    cache: DiskCache,
    source_id: str,
    partition_key: str,
    suffix: str,
    noticed_on: date,
    ask: Callable[[Mapping[str, str]], Answer | None],
    content: Callable[[bytes], bytes] = unchanged,
) -> bytes | None:
    """Ask again for a held file; a changed one is held dated `noticed_on` and returned.

    A file held without validators is asked for in full and compared by `content`, which reads
    what a file holds, so an archive packed again around the same file is no change.
    """
    held = cache.latest(source_id, partition_key, suffix)
    if held is None:
        return None
    answer = ask(cache.read_validators(source_id, partition_key, suffix))
    if answer is None:
        return None
    changed = content(answer.content) != content(held)
    if changed:
        cache.write_version(source_id, partition_key, suffix, noticed_on, answer.content)
    # Held only once the answer has been read, so a page served in place of the file never stands
    # for the version held.
    cache.write_validators(source_id, partition_key, suffix, answer.validators)
    return answer.content if changed else None
