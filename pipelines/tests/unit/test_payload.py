"""What every parser does with a response it cannot read.

A caller reading years of days recognises a source failure and records the day. Anything else
ends the run and discards what it had already read, which is how a thousand days of reading were
lost to one file.
"""

from collections.abc import Callable

import pytest

from pipelines.sources.bse.corporate_actions import parse_actions
from pipelines.sources.delivery import parse_bse_delivery, parse_nse_delivery
from pipelines.sources.errors import SchemaDrift, SourceError
from pipelines.sources.legacy import parse_bse_legacy, parse_nse_legacy
from pipelines.sources.payload import decoded
from pipelines.sources.udiff import parse_udiff

# Shapes the venues have answered with in place of the file asked for.
UNREADABLE = {
    # The opening bytes NSE served in place of the delivery file on 2022-08-08.
    "a spreadsheet": (
        b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00LA\x02\x11_\x01\x00\x00\x90\x04\x00\x00"
        b"\x13\x00\x08\x02[Content_Types].xml \xa2\x04\x02(\xa0\x00\x02\x00\x00\x00"
    ),
    "a page": b"<!DOCTYPE html><html><head><title>BSE</title></head></html>",
    "bytes that are not text": b"\xff\xfe\x00\x01\x02\x03",
    "nothing at all": b"",
    "a file of another kind": b"one,two,three\n1,2,3\n",
}

PARSERS: dict[str, Callable[[bytes], object]] = {
    "bse legacy": parse_bse_legacy,
    "nse legacy": parse_nse_legacy,
    "udiff": parse_udiff,
    "nse delivery": parse_nse_delivery,
    "bse delivery": parse_bse_delivery,
    "corporate actions": parse_actions,
}


@pytest.mark.parametrize("parser", PARSERS.values(), ids=list(PARSERS))
@pytest.mark.parametrize("payload", UNREADABLE.values(), ids=list(UNREADABLE))
def test_a_response_a_parser_cannot_read_is_a_source_failure(
    parser: Callable[[bytes], object], payload: bytes
) -> None:
    with pytest.raises(SourceError):
        parser(payload)


def test_a_response_that_is_not_text_names_the_shape_it_arrived_in() -> None:
    """NSE served the delivery file as a spreadsheet on 2022-08-08."""
    with pytest.raises(SchemaDrift) as refused:
        decoded(UNREADABLE["a spreadsheet"], "nse delivery")

    assert "an archive" in str(refused.value)


def test_a_response_that_is_text_is_returned_unchanged() -> None:
    assert decoded("SYMBOL,SERIES\n".encode("utf-8-sig"), "nse delivery") == "SYMBOL,SERIES\n"
