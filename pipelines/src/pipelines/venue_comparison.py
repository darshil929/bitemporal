"""Each bar compared with the other venue's close of the same day, over the series arrays.

The spread is the one `int_venue_spread` holds: the gap between the two closes in basis points of
their midpoint, rounded to four decimals, where both venues published a close under the same ISIN.
The venues diverge as trading day validation judges a day: beyond its limit, where both traded at
least its turnover and closed at no less than its price.
"""

import numpy as np
import numpy.typing as npt

from pipelines.validation import (
    BASIS_POINTS,
    COMPARABLE_PRICE,
    COMPARABLE_TURNOVER,
    DIVERGENCE_LIMIT_BPS,
)

# A day sits below an instrument's position in one int64 key.
DAY_BITS = 32
SPREAD_DECIMALS = 4

Ints = npt.NDArray[np.int64]
Floats = npt.NDArray[np.float64]
Flags = npt.NDArray[np.bool_]


def day_keys(instrument: Ints, day: Ints) -> Ints:
    """One key per bar, rising with the instrument's position and then the day."""
    keys: Ints = (instrument << DAY_BITS) + day
    return keys


def venue_spread(
    keys: Ints,
    is_nse: Flags,
    source_isin: npt.NDArray[np.bytes_],
    close: Floats,
    turnover: Floats,
) -> tuple[Floats, Flags]:
    """Each bar's spread to the other venue's close that day, and whether the two diverge.

    The keys rise within each venue's bars. A bar the other venue has no close beside reads NaN
    and does not diverge; a missing turnover counts as none.
    """
    spread = np.full(len(keys), np.nan)
    diverging = np.zeros(len(keys), dtype=bool)
    bse = np.flatnonzero(~is_nse)
    nse = np.flatnonzero(is_nse)
    if not len(bse) or not len(nse):
        return spread, diverging
    position = np.searchsorted(keys[nse], keys[bse]).clip(max=len(nse) - 1)
    paired = keys[nse][position] == keys[bse]
    bse, nse = bse[paired], nse[position[paired]]
    priced = (source_isin[bse] == source_isin[nse]) & ~np.isnan(close[bse]) & ~np.isnan(close[nse])
    bse, nse = bse[priced], nse[priced]

    gap = float(BASIS_POINTS) * np.abs(close[bse] - close[nse]) / ((close[bse] + close[nse]) / 2)
    thinner = np.minimum(np.nan_to_num(turnover[bse]), np.nan_to_num(turnover[nse]))
    diverges = (
        (gap > float(DIVERGENCE_LIMIT_BPS))
        & (thinner >= float(COMPARABLE_TURNOVER))
        & (np.minimum(close[bse], close[nse]) >= float(COMPARABLE_PRICE))
    )
    for side in (bse, nse):
        spread[side] = np.round(gap, SPREAD_DECIMALS)
        diverging[side] = diverges
    return spread, diverging
