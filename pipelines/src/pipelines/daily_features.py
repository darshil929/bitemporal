"""Writes of the daily features, each computation replacing every stored row.

The table is emptied and every batch of rows inserted in one transaction, so a reader waits while a
replacement runs and then sees the new computation whole. The rows of an instrument the computation
no longer holds, such as an ISIN superseded at a split, leave with the rest. Rows reach a temporary
table through a binary COPY, a blank figure travelling as NaN, and are stored with blanks as nulls.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import psycopg

# The engine's columns, in the order of the rows of `DailyFeatureRows.figures`.
ENGINE_COLUMNS = (
    "change_1d",
    "return_1d",
    "return_1w",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_1y",
    "momentum_12_1",
    "volatility_20d",
    "rsi_14",
    "adtv_20d",
    "volume_ratio_20d",
    "delivery_pct_1d",
    "delivery_pct_20d",
    "from_52w_high",
    "is_52w_high",
    "is_52w_low",
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_20",
    "ema_50",
    "bollinger_20_upper",
    "bollinger_20_lower",
)
# Columns the engine writes as 1 or 0.
FLAG_COLUMNS = frozenset({"is_52w_high", "is_52w_low"})

INCOMING = "incoming_daily_features"
ROWS_PER_COPY_BLOCK = 50_000


class FeatureWriteRefused(Exception):
    """Rows whose columns differ in length."""


@dataclass(frozen=True)
class DailyFeatureRows:
    """Rows in columns, one entry per row; a figure is NaN where it is blank."""

    isin: Sequence[str]
    trade_date: npt.NDArray[np.datetime64]
    as_of_date: npt.NDArray[np.datetime64]
    primary_venue: Sequence[str]
    close: npt.NDArray[np.float64]
    figures: npt.NDArray[np.float64]
    venue_spread_bps: npt.NDArray[np.float64]
    is_day_complete: npt.NDArray[np.bool_]
    is_diverging: npt.NDArray[np.bool_]


def _stored(column: str) -> str:
    if column in FLAG_COLUMNS:
        return f"nullif({column}, 'NaN') = 1"
    return f"nullif({column}, 'NaN')"


ENGINE_LIST = ", ".join(ENGINE_COLUMNS)
CREATE_INCOMING = (
    f"create temporary table {INCOMING} (isin text, trade_date date, as_of_date date,"
    f" primary_venue text, close float8, "
    + ", ".join(f"{column} float8" for column in ENGINE_COLUMNS)
    + ", venue_spread_bps float8, is_day_complete bool, is_diverging bool)"
)
COPY_INCOMING = f"copy {INCOMING} from stdin (format binary)"
INCOMING_TYPES = (
    ["text", "date", "date", "text", "float8"]
    + ["float8"] * len(ENGINE_COLUMNS)
    + ["float8", "bool", "bool"]
)
STORE_INCOMING = (
    "insert into mart_daily_features (isin, trade_date, as_of_date, primary_venue, close,"
    f" {ENGINE_LIST}, venue_spread_bps, is_day_complete, is_diverging)"
    " select isin, trade_date, as_of_date, primary_venue, round(close::numeric, 4), "
    + ", ".join(_stored(column) for column in ENGINE_COLUMNS)
    + f", nullif(venue_spread_bps, 'NaN'), is_day_complete, is_diverging from {INCOMING}"
)


def _check(rows: DailyFeatureRows) -> int:
    count = len(rows.isin)
    lengths = {
        len(rows.trade_date),
        len(rows.as_of_date),
        len(rows.primary_venue),
        len(rows.close),
        len(rows.venue_spread_bps),
        len(rows.is_day_complete),
        len(rows.is_diverging),
    }
    if lengths != {count} or rows.figures.shape != (len(ENGINE_COLUMNS), count):
        raise FeatureWriteRefused(
            f"columns of {count} rows do not match: lengths {sorted(lengths)},"
            f" figures {rows.figures.shape}"
        )
    return count


def _copy(cursor: psycopg.Cursor[tuple[object, ...]], rows: DailyFeatureRows, count: int) -> None:
    with cursor.copy(COPY_INCOMING) as copy:
        copy.set_types(INCOMING_TYPES)
        for start in range(0, count, ROWS_PER_COPY_BLOCK):
            block = slice(start, start + ROWS_PER_COPY_BLOCK)
            for isin, trade_day, known, venue, close, figures, spread, complete, diverging in zip(
                rows.isin[block],
                rows.trade_date[block].tolist(),
                rows.as_of_date[block].tolist(),
                rows.primary_venue[block],
                rows.close[block].tolist(),
                rows.figures[:, block].T.tolist(),
                rows.venue_spread_bps[block].tolist(),
                rows.is_day_complete[block].tolist(),
                rows.is_diverging[block].tolist(),
                strict=True,
            ):
                copy.write_row(
                    (isin, trade_day, known, venue, close, *figures, spread, complete, diverging)
                )


def replace_daily_features(
    connection: psycopg.Connection, batches: Iterable[DailyFeatureRows]
) -> int:
    """Replace every stored row with the rows of `batches` and count those written."""
    written = 0
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("truncate mart_daily_features")
        cursor.execute(CREATE_INCOMING)
        for rows in batches:
            count = _check(rows)
            _copy(cursor, rows, count)
            cursor.execute(STORE_INCOMING)
            written += cursor.rowcount
            cursor.execute(f"truncate {INCOMING}")
        # The caller's transaction can stay open after the replacement returns.
        cursor.execute(f"drop table {INCOMING}")
    return written
