"""The daily feature rows of every instrument, derived from both venues' whole series.

Each venue's series is computed whole and an instrument's row on a day takes the values of the
venue designated that day, so no window mixes the venues. A day the designated venue did not
trade, or traded without a close, has no row.

A row is dated by the latest of: the bars of both venues up to its day, the actions applied on or
before its day, and its day's verdict. An action after the day rescales earlier prices alone, which
no figure reads, since levels are in their own day's price scale.
"""

import logging
from collections.abc import Iterator

import numpy as np
import numpy.typing as npt

import btcore
from pipelines.daily_features import ENGINE_COLUMNS, DailyFeatureRows
from pipelines.feature_inputs import ActionDates, ContinuousSeries, Verdicts
from pipelines.venue_comparison import DAY_BITS, day_keys, venue_spread

logger = logging.getLogger(__name__)

INSTRUMENTS_PER_BATCH = 500

Ints = npt.NDArray[np.int64]
Flags = npt.NDArray[np.bool_]


class DerivationRefused(Exception):
    """Inputs that cannot become rows: a designated bar on a day without a verdict, or engine
    columns other than the stored ones."""


def instrument_bounds(isin: npt.NDArray[np.bytes_]) -> Ints:
    """The first bar of each instrument, then the end of the last."""
    changes = np.flatnonzero(isin[1:] != isin[:-1]) + 1
    return np.concatenate(([0], changes, [len(isin)])).astype(np.int64)


def venue_pairs(is_nse: Flags, bounds: Ints) -> Ints:
    """Offsets of each instrument's BSE series, then its NSE series, either possibly empty."""
    bse_bars = np.add.reduceat((~is_nse).astype(np.int64), bounds[:-1])
    offsets = np.empty(2 * len(bse_bars) + 1, dtype=np.int64)
    offsets[0:-1:2] = bounds[:-1]
    offsets[1::2] = bounds[:-1] + bse_bars
    offsets[-1] = bounds[-1]
    return offsets


def running_latest(keys: Ints, known: Ints) -> Ints:
    """For each entry, the latest of `known` over its instrument's entries keyed at or before it.

    A key holds the instrument's position above `DAY_BITS` and the day below.
    """
    order = np.argsort(keys, kind="stable")
    instrument = (keys[order] >> DAY_BITS) << DAY_BITS
    latest: Ints = np.maximum.accumulate(instrument + known[order]) - instrument
    through: Ints = latest[np.searchsorted(keys[order], keys, side="right") - 1]
    return through


def latest_action(actions: ActionDates, isins: npt.NDArray[np.bytes_], keys: Ints) -> Ints:
    """For each key, the latest date known among its instrument's actions on or before its day,
    0 where none; `isins` names the instruments, in order, by their positions in the keys."""
    held = slice(
        np.searchsorted(actions.isin, isins[0]), np.searchsorted(actions.isin, isins[-1], "right")
    )
    position = np.searchsorted(isins, actions.isin[held]).clip(max=len(isins) - 1)
    ours = isins[position] == actions.isin[held]
    action_keys = day_keys(position[ours].astype(np.int64), actions.ex_day[held][ours])
    if not len(action_keys):
        return np.zeros(len(keys), dtype=np.int64)
    latest = running_latest(action_keys, actions.as_of_day[held][ours])
    last = np.searchsorted(action_keys, keys, side="right") - 1
    applies = (last >= 0) & ((action_keys[last.clip(min=0)] >> DAY_BITS) == (keys >> DAY_BITS))
    return np.where(applies, latest[last.clip(min=0)], 0)


def day_verdicts(verdicts: Verdicts, is_nse: Flags, day: Ints) -> tuple[Flags, Ints]:
    """Whether each venue's day was complete, and when that verdict was known."""
    verdict_keys = day_keys(verdicts.is_nse.astype(np.int64), verdicts.day)
    keys = day_keys(is_nse.astype(np.int64), day)
    if not len(verdict_keys):
        found = np.zeros(len(keys), dtype=bool)
        position = np.zeros(len(keys), dtype=np.int64)
    else:
        position = np.searchsorted(verdict_keys, keys).clip(max=len(verdict_keys) - 1)
        found = verdict_keys[position] == keys
    if missing := len(keys) - int(np.count_nonzero(found)):
        raise DerivationRefused(f"{missing} designated bars fall on days without a verdict")
    return verdicts.is_complete[position], verdicts.as_of_day[position]


def _batch(
    series: ContinuousSeries,
    actions: ActionDates,
    verdicts: Verdicts,
    bars: slice,
    bounds: Ints,
    threads: int,
) -> DailyFeatureRows:
    is_nse = series.is_nse[bars]
    day = series.day[bars]
    turnover = series.turnover[bars]
    offsets = venue_pairs(is_nse, bounds)
    designated = btcore.designated_bars(day, turnover, offsets, threads=threads) == 1
    figures = btcore.daily_features(
        series.close[bars],
        series.high[bars],
        series.low[bars],
        series.volume[bars],
        series.delivery[bars],
        turnover,
        series.adjustment_factor[bars],
        offsets=offsets,
        threads=threads,
    )
    close = series.close_as_traded[bars]
    keep = designated & ~np.isnan(close)
    if unpriced := int(np.count_nonzero(designated & np.isnan(close))):
        logger.info("designated bars without a close left out", extra={"bars": unpriced})

    instrument = np.repeat(np.arange(len(bounds) - 1, dtype=np.int64), np.diff(bounds))
    keys = day_keys(instrument, day)
    spread, diverging = venue_spread(keys, is_nse, series.source_isin[bars], close, turnover)
    is_complete, verdict_known = day_verdicts(verdicts, is_nse[keep], day[keep])
    isin = series.isin[bars]
    known = np.maximum.reduce(
        [
            running_latest(keys, series.as_of_day[bars])[keep],
            latest_action(actions, isin[bounds[:-1]], keys[keep]),
            verdict_known,
        ]
    )
    return DailyFeatureRows(
        isin=np.char.decode(isin[keep], "ascii").tolist(),
        trade_date=day[keep].astype("datetime64[D]"),
        as_of_date=known.astype("datetime64[D]"),
        primary_venue=np.where(is_nse[keep], "NSE", "BSE").tolist(),
        close=close[keep],
        figures=figures[:, keep],
        venue_spread_bps=spread[keep],
        is_day_complete=is_complete,
        is_diverging=diverging[keep],
    )


def derive_daily_features(
    series: ContinuousSeries,
    actions: ActionDates,
    verdicts: Verdicts,
    instruments_per_batch: int = INSTRUMENTS_PER_BATCH,
    threads: int = 0,
) -> Iterator[DailyFeatureRows]:
    """The rows of every instrument, a batch of instruments at a time."""
    if tuple(btcore.FEATURE_COLUMNS) != ENGINE_COLUMNS:
        raise DerivationRefused(f"engine columns {btcore.FEATURE_COLUMNS} differ from the table's")
    bounds = instrument_bounds(series.isin)
    for first in range(0, len(bounds) - 1, instruments_per_batch):
        batch = bounds[first : first + instruments_per_batch + 1]
        yield _batch(
            series, actions, verdicts, slice(batch[0], batch[-1]), batch - batch[0], threads
        )
