# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["numpy>=2,<3", "ta-lib==0.8.1"]
# ///
"""Expected values for the engine's golden tests, one file per family of computations.

Each computation is taken from golden_ohlcv.csv twice: by a plain NumPy implementation written for
clarity rather than speed, and by TA-Lib where TA-Lib has it. Where both exist they must agree within
the family's tolerance or nothing is written, and the file holds TA-Lib's value. The versions are
pinned here and in generate_golden.py.lock, so the files change only when this file or the input does:

    uv run --script engine/tests/golden/generate_golden.py

Where a pinned definition departs from TA-Lib 0.8.1, those rows hold the NumPy value alone:

- RSI is blank while the close has not changed since the series' first bar, where TA-Lib gives 0
"""

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import talib

HERE = Path(__file__).resolve().parent
INPUT = HERE / "golden_ohlcv.csv"
NUMERIC = ["open", "high", "low", "close", "volume", "turnover", "delivery", "factor"]

type Columns = dict[str, np.ndarray]
type Computation = Callable[[Columns], np.ndarray]


@dataclass(frozen=True)
class Expected:
    """One expected column: its plain implementation and, where TA-Lib has it, TA-Lib's."""

    name: str
    numpy: Computation
    talib: Computation | None = None
    departs: Computation | None = None
    """The rows where the pinned definition departs from TA-Lib."""


@dataclass(frozen=True)
class Family:
    """The columns of one expected file, held to one relative tolerance between the references."""

    file: str
    tolerance: float
    columns: list[Expected]


def numpy_sma(close: np.ndarray, period: int) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    for end in range(period, close.size + 1):
        out[end - 1] = close[end - period : end].mean()
    return out


def numpy_ema(close: np.ndarray, period: int) -> np.ndarray:
    """Seeded with the simple average of the first window, as TA-Lib seeds it."""
    out = np.full(close.shape, np.nan)
    if close.size < period:
        return out
    k = 2.0 / (period + 1)
    value = close[:period].mean()
    out[period - 1] = value
    for index in range(period, close.size):
        value = value + k * (close[index] - value)
        out[index] = value
    return out


def numpy_wma(close: np.ndarray, period: int) -> np.ndarray:
    weights = np.arange(1, period + 1, dtype=float)
    out = np.full(close.shape, np.nan)
    for end in range(period, close.size + 1):
        out[end - 1] = (close[end - period : end] * weights).sum() / weights.sum()
    return out


def moving_averages() -> Family:
    columns = []
    for period in (20, 50, 200):
        columns.append(
            Expected(
                f"sma_{period}",
                numpy=lambda c, p=period: numpy_sma(c["close"], p),
                talib=lambda c, p=period: talib.SMA(c["close"], timeperiod=p),
            )
        )
    for period in (20, 50):
        columns.append(
            Expected(
                f"ema_{period}",
                numpy=lambda c, p=period: numpy_ema(c["close"], p),
                talib=lambda c, p=period: talib.EMA(c["close"], timeperiod=p),
            )
        )
    columns.append(
        Expected(
            "wma_20",
            numpy=lambda c: numpy_wma(c["close"], 20),
            talib=lambda c: talib.WMA(c["close"], timeperiod=20),
        )
    )
    return Family("golden_moving_averages.csv", 1e-12, columns)


def numpy_rsi(close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's averages seeded with the mean of the first period changes, blank while both are 0."""
    out = np.full(close.shape, np.nan)
    change = np.diff(close)
    gain = np.maximum(change, 0.0)
    loss = np.maximum(-change, 0.0)
    if change.size < period:
        return out
    average_gain = gain[:period].mean()
    average_loss = loss[:period].mean()
    for index in range(period, close.size):
        if index > period:
            average_gain = (average_gain * (period - 1) + gain[index - 1]) / period
            average_loss = (average_loss * (period - 1) + loss[index - 1]) / period
        movement = average_gain + average_loss
        out[index] = 100 * average_gain / movement if movement > 0 else np.nan
    return out


def unchanged_since_first_bar(close: np.ndarray) -> np.ndarray:
    return ~np.logical_or.accumulate(close != close[0])


def relative_strength() -> Family:
    return Family(
        "golden_relative_strength.csv",
        1e-12,
        [
            Expected(
                f"rsi_{period}",
                numpy=lambda c, p=period: numpy_rsi(c["close"], p),
                talib=lambda c, p=period: talib.RSI(c["close"], timeperiod=p),
                departs=lambda c: unchanged_since_first_bar(c["close"]),
            )
            for period in (2, 14)
        ],
    )


def numpy_variance(close: np.ndarray, period: int, ddof: int) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    for end in range(period, close.size + 1):
        out[end - 1] = close[end - period : end].var(ddof=ddof)
    return out


def variances() -> Family:
    """TA-Lib keeps running sums, within 1e-11 of the two-pass variance on these series."""
    return Family(
        "golden_variance.csv",
        1e-11,
        [
            Expected(
                "variance_20",
                numpy=lambda c: numpy_variance(c["close"], 20, ddof=0),
                talib=lambda c: talib.VAR(c["close"], timeperiod=20, nbdev=1),
            ),
            Expected("sample_variance_20", numpy=lambda c: numpy_variance(c["close"], 20, ddof=1)),
        ],
    )


def numpy_bollinger(close: np.ndarray, period: int, width: float, sign: int) -> np.ndarray:
    return numpy_sma(close, period) + sign * width * np.sqrt(numpy_variance(close, period, ddof=0))


def price_bands() -> Family:
    def talib_band(line: int) -> Computation:
        return lambda c: talib.BBANDS(c["close"], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)[
            line
        ]

    return Family(
        "golden_price_bands.csv",
        1e-12,
        [
            Expected(
                "bollinger_20_upper",
                numpy=lambda c: numpy_bollinger(c["close"], 20, 2.0, 1),
                talib=talib_band(0),
            ),
            Expected(
                "bollinger_20_lower",
                numpy=lambda c: numpy_bollinger(c["close"], 20, 2.0, -1),
                talib=talib_band(2),
            ),
        ],
    )


def numpy_return(close: np.ndarray, bars: int, skip: int) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    for index in range(bars + skip, close.size):
        later, earlier = close[index - skip], close[index - skip - bars]
        out[index] = (later - earlier) / earlier
    return out


def lagged(values: np.ndarray, skip: int) -> np.ndarray:
    kept = max(values.size - skip, 0)
    return np.concatenate([np.full(values.size - kept, np.nan), values[:kept]])


def returns() -> Family:
    return Family(
        "golden_returns.csv",
        1e-12,
        [
            *(
                Expected(
                    f"return_{bars}",
                    numpy=lambda c, b=bars: numpy_return(c["close"], b, 0),
                    talib=lambda c, b=bars: talib.ROCP(c["close"], timeperiod=b),
                )
                for bars in (1, 252)
            ),
            Expected(
                "momentum_12_1",
                numpy=lambda c: numpy_return(c["close"], 231, 21),
                talib=lambda c: lagged(talib.ROCP(c["close"], timeperiod=231), 21),
            ),
        ],
    )


def numpy_volatility(close: np.ndarray, period: int, periods_per_year: int) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    log_returns = np.log1p(np.diff(close) / close[:-1])
    for end in range(period, close.size):
        out[end] = log_returns[end - period : end].std(ddof=1) * np.sqrt(periods_per_year)
    return out


def price_changes() -> Family:
    return Family(
        "golden_price_changes.csv",
        1e-12,
        [
            Expected(
                "change_1",
                numpy=lambda c: np.concatenate([[np.nan], np.diff(c["close"])]),
                talib=lambda c: talib.MOM(c["close"], timeperiod=1),
            )
        ],
    )


def numpy_extreme(
    values: np.ndarray, period: int, pick: Callable[[np.ndarray], float]
) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    for end in range(period, values.size + 1):
        out[end - 1] = pick(values[end - period : end])
    return out


def range_extremes() -> Family:
    return Family(
        "golden_range_extremes.csv",
        1e-12,
        [
            *(
                Expected(
                    f"maximum_{period}",
                    numpy=lambda c, p=period: numpy_extreme(c["high"], p, np.max),
                    talib=lambda c, p=period: talib.MAX(c["high"], timeperiod=p),
                )
                for period in (20, 252)
            ),
            Expected(
                "minimum_20",
                numpy=lambda c: numpy_extreme(c["low"], 20, np.min),
                talib=lambda c: talib.MIN(c["low"], timeperiod=20),
            ),
        ],
    )


def numpy_new_extreme(
    values: np.ndarray, period: int, pick: Callable[[np.ndarray], float]
) -> np.ndarray:
    extremes = numpy_extreme(values, period, pick)
    return np.where(np.isnan(extremes), np.nan, (values == extremes).astype(float))


def talib_new_extreme(values: np.ndarray, extremes: np.ndarray) -> np.ndarray:
    return np.where(np.isnan(extremes), np.nan, (values == extremes).astype(float))


def range_positions() -> Family:
    def numpy_distance(c: Columns) -> np.ndarray:
        highest = numpy_extreme(c["high"], 252, np.max)
        return (c["close"] - highest) / highest

    def talib_distance(c: Columns) -> np.ndarray:
        highest = talib.MAX(c["high"], timeperiod=252)
        return (c["close"] - highest) / highest

    return Family(
        "golden_range_positions.csv",
        1e-12,
        [
            Expected("from_52w_high", numpy=numpy_distance, talib=talib_distance),
            Expected(
                "is_52w_high",
                numpy=lambda c: numpy_new_extreme(c["high"], 252, np.max),
                talib=lambda c: talib_new_extreme(c["high"], talib.MAX(c["high"], timeperiod=252)),
            ),
            Expected(
                "is_52w_low",
                numpy=lambda c: numpy_new_extreme(c["low"], 252, np.min),
                talib=lambda c: talib_new_extreme(c["low"], talib.MIN(c["low"], timeperiod=252)),
            ),
        ],
    )


def volatilities() -> Family:
    """NumPy alone: TA-Lib has no realised volatility."""
    return Family(
        "golden_volatility.csv",
        1e-12,
        [Expected("volatility_20", numpy=lambda c: numpy_volatility(c["close"], 20, 252))],
    )


FAMILIES = [
    moving_averages(),
    relative_strength(),
    variances(),
    price_bands(),
    returns(),
    price_changes(),
    volatilities(),
    range_extremes(),
    range_positions(),
]


class ReferencesDisagree(Exception):
    """TA-Lib and the plain implementation give different values for one column of one series."""


def read_series() -> list[tuple[str, list[str], Columns]]:
    """Each series in file order, with its trade dates and numeric columns."""
    with INPUT.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    series = []
    for name in dict.fromkeys(row["series"] for row in rows):
        own = [row for row in rows if row["series"] == name]
        columns = {
            column: np.array([float(row[column]) if row[column] else math.nan for row in own])
            for column in NUMERIC
        }
        series.append((name, [row["trade_date"] for row in own], columns))
    return series


def agreed(family: Family, expected: Expected, series: str, inputs: Columns) -> np.ndarray:
    plain = expected.numpy(inputs)
    if expected.talib is None:
        return plain
    reference = np.asarray(expected.talib(inputs), dtype=float)
    if expected.departs is not None:
        reference = np.where(expected.departs(inputs), plain, reference)
    if not np.allclose(reference, plain, rtol=family.tolerance, atol=0.0, equal_nan=True):
        worst = int(np.nanargmax(np.abs(reference - plain) / np.abs(plain)))
        raise ReferencesDisagree(
            f"{expected.name} on {series} at row {worst}: TA-Lib {reference[worst]!r}, "
            f"NumPy {plain[worst]!r}"
        )
    return reference


def written(value: float) -> str:
    return "" if math.isnan(value) else repr(float(value))


def main() -> None:
    series = read_series()
    for family in FAMILIES:
        with (HERE / family.file).open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["series", "trade_date", *(column.name for column in family.columns)])
            for name, dates, inputs in series:
                values = [agreed(family, column, name, inputs) for column in family.columns]
                for index, date in enumerate(dates):
                    writer.writerow([name, date, *(written(column[index]) for column in values)])


if __name__ == "__main__":
    main()
