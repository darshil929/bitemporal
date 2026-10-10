"""Bars compared with the other venue's close of the same day."""

import numpy as np
import pytest

from pipelines.venue_comparison import day_keys, venue_spread

RELIANCE = b"INE002A01018"
SHRIRAM_BEFORE_SPLIT = b"INE721A01013"
SHRIRAM = b"INE721A01047"


def compared(
    closes: list[float],
    venues: list[str],
    turnover: float = 3e6,
    sources: list[bytes] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """One instrument's bars on one day, BSE's first."""
    count = len(closes)
    return venue_spread(
        day_keys(np.zeros(count, dtype=np.int64), np.full(count, 20_453, dtype=np.int64)),
        np.array([venue == "NSE" for venue in venues]),
        np.array(sources or [RELIANCE] * count, dtype="S12"),
        np.array(closes),
        np.full(count, turnover),
    )


@pytest.mark.parametrize(
    ("bse_close", "nse_close", "turnover", "diverging"),
    [
        (100.0, 106.0, 3e6, True),
        (100.0, 106.0, 2e6, False),
        (9.0, 9.6, 3e6, False),
        (100.0, 104.0, 3e6, False),
    ],
)
def test_the_venues_diverge_as_trading_day_validation_judges(
    bse_close: float, nse_close: float, turnover: float, diverging: bool
) -> None:
    spread, diverges = compared([bse_close, nse_close], ["BSE", "NSE"], turnover)

    gap = 10000 * abs(bse_close - nse_close) / ((bse_close + nse_close) / 2)
    assert spread.tolist() == [round(gap, 4)] * 2
    assert diverges.tolist() == [diverging] * 2


def test_a_venue_alone_has_no_spread() -> None:
    spread, diverges = compared([100.0], ["NSE"])

    assert np.isnan(spread[0])
    assert not diverges[0]


def test_a_venue_without_a_close_leaves_no_spread() -> None:
    spread, _ = compared([100.0, np.nan], ["BSE", "NSE"])

    assert np.isnan(spread).all()


def test_closes_published_under_different_isins_are_not_compared() -> None:
    spread, _ = compared([100.0, 101.0], ["BSE", "NSE"], sources=[SHRIRAM_BEFORE_SPLIT, SHRIRAM])

    assert np.isnan(spread).all()
