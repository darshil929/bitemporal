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
        # Genus Power's T+0 line, 130343, comes first in the file and traded 24 shares.
        ("20250616.csv", date(2025, 6, 16), "530343", 112_827),
        # State Bank's T+0 line was numbered 100112 in the format BSE published before July 2024.
        ("20240328_legacy.csv", date(2024, 3, 28), "500112", 873_887),
        # HDFC Bank's deal window, 600180, traded 2,183 times at 1,342.95 against 1,699 at 1,181.
        ("20161216_legacy.csv", date(2016, 12, 16), "500180", 65_262),
        # Emami's window under a code of its own traded 61,180 shares in 97 trades.
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
    """Genus Power's T+0 line spells the name in mixed case, and its ordinary line in capitals."""
    rows = recorded("20250616.csv", date(2025, 6, 16))

    assert names_by_isin(rows, "BSE") == {"INE955D01029": "GENUS POWER INFRASTRUCTURES LT"}


def test_a_day_listing_each_isin_once_keeps_every_bar() -> None:
    lines = normalize(recorded("20260814.csv", date(2026, 8, 14)), "BSE")

    assert ordinary_lines(lines) == lines
