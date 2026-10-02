"""An ISIN a venue lists on more than one security line is stored from its ordinary line."""

from datetime import date
from pathlib import Path

import pytest

from pipelines.sources.bhavcopy import BhavcopyRow, names_by_isin, normalize, ordinary_lines
from pipelines.sources.legacy import parse_bse_legacy
from pipelines.sources.udiff import parse_udiff

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "bse_bhavcopy_equity"


def recorded(name: str, trade_date: date) -> tuple[BhavcopyRow, ...]:
    payload = (CASSETTES / name).read_bytes()
    if name.endswith("_legacy.csv"):
        return parse_bse_legacy(payload, trade_date)
    return parse_udiff(payload)


@pytest.mark.parametrize(
    ("name", "trade_date", "scrip_code", "volume"),
    [
        # A T+0 line, numbered with a leading 1, listed first in the file and trading little.
        ("20250616.csv", date(2025, 6, 16), "530343", 112_827),
        # A T+0 line in BSE's legacy format.
        ("20240328_legacy.csv", date(2024, 3, 28), "500112", 873_887),
        # A deal window, numbered with a leading 6, trading more often at a higher price than the
        # ordinary line.
        ("20161216_legacy.csv", date(2016, 12, 16), "500180", 65_262),
        # A window under a code of its own, trading more shares than the ordinary line.
        ("20230413_legacy.csv", date(2023, 4, 13), "531162", 2_898),
    ],
)
def test_the_ordinary_line_is_the_bar(
    name: str, trade_date: date, scrip_code: str, volume: int
) -> None:
    lines = normalize(recorded(name, trade_date), "BSE")

    bars = ordinary_lines(lines)

    assert len(lines) == 2
    assert [(bar.scrip_code, bar.volume) for bar in bars] == [(scrip_code, volume)]


def test_the_ordinary_line_names_the_instrument() -> None:
    """The ordinary line names the instrument, where a T+0 line spells the name in mixed case."""
    rows = recorded("20250616.csv", date(2025, 6, 16))

    assert names_by_isin(rows, "BSE") == {"INE955D01029": "GENUS POWER INFRASTRUCTURES LT"}


def test_a_day_listing_each_isin_once_keeps_every_bar() -> None:
    lines = normalize(recorded("20260814.csv", date(2026, 8, 14)), "BSE")

    assert ordinary_lines(lines) == lines
