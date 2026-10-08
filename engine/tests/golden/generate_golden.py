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


FAMILIES = [moving_averages()]


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
