"""The inputs of the daily features, read from the transform layer into NumPy arrays.

The continuous series crosses in one binary COPY whose rows all have the same width, a value that
may be missing travelling as NaN, so the stream is cut into columns without a Python object per
value. ISINs are ordered by their bytes, as NumPy compares them.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import numpy.typing as npt
import psycopg

# Postgres counts binary dates from 2000-01-01; the arrays count days from 1970-01-01.
POSTGRES_EPOCH_DAY = 10_957
COPY_HEADER = b"PGCOPY\n\xff\r\n\x00" + bytes(8)
COPY_TRAILER = b"\xff\xff"
COPY_BLOCK_BYTES = 64 * 1024 * 1024
# The ordered read sorts the whole series, which spills to disk in less memory than this.
SERIES_SORT_MEMORY = "512MB"

MEASURES = (
    "close",
    "high",
    "low",
    "volume",
    "delivery",
    "turnover",
    "adjustment_factor",
    "close_as_traded",
)


# Each field of a binary COPY row: its length, then its value, big-endian.
SERIES_FIELDS: dict[str, str] = {
    "isin": "S12",
    "source_isin": "S12",
    "venue": "S3",
    "trade_date": ">i4",
    "as_of_date": ">i4",
    **{measure: ">f8" for measure in MEASURES},
}
SERIES_ROW = np.dtype(
    [("field_count", ">i2")]
    + [
        part
        for name, kind in SERIES_FIELDS.items()
        for part in ((f"{name}_length", ">i4"), (name, kind))
    ]
)

SERIES_COPY = (
    "copy (select isin, source_isin, venue, trade_date, as_of_date,"
    " coalesce(close::float8, 'NaN'), high::float8, low::float8, volume::float8,"
    " coalesce(delivery_quantity::float8, 'NaN'), coalesce(turnover::float8, 'NaN'),"
    " adjustment_factor::float8, coalesce(close_as_traded::float8, 'NaN')"
    ' from int_continuous_prices order by isin collate "C", venue, trade_date)'
    " to stdout (format binary)"
)
ACTIONS_QUERY = (
    "select isin, ex_date, as_of_date from int_capital_action_factors"
    ' where applied_factor is not null order by isin collate "C", ex_date'
)
VERDICTS_QUERY = (
    "select venue = 'NSE', trade_date, is_complete, as_of_date from stg_trading_day"
    " order by venue, trade_date"
)

Ints = npt.NDArray[np.int64]
Floats = npt.NDArray[np.float64]
Isins = npt.NDArray[np.bytes_]


class SeriesUnreadable(Exception):
    """A continuous series stream of another shape than the one read here."""


@dataclass(frozen=True)
class ContinuousSeries:
    """Every bar of the continuous series, by instrument, venue and day; NaN where missing.

    Days count from 1970-01-01. `isin` is the ISIN the instrument trades under now and
    `source_isin` the one the bar was published under.
    """

    isin: Isins
    source_isin: Isins
    is_nse: npt.NDArray[np.bool_]
    day: Ints
    as_of_day: Ints
    close: Floats
    high: Floats
    low: Floats
    volume: Floats
    delivery: Floats
    turnover: Floats
    adjustment_factor: Floats
    close_as_traded: Floats


@dataclass(frozen=True)
class ActionDates:
    """Each ex-date the continuous series applies a factor on, by instrument, and the day it was
    known."""

    isin: Isins
    ex_day: Ints
    as_of_day: Ints


@dataclass(frozen=True)
class Verdicts:
    """Each venue's latest verdict on each day, BSE's days first, and the day it was known."""

    is_nse: npt.NDArray[np.bool_]
    day: Ints
    is_complete: npt.NDArray[np.bool_]
    as_of_day: Ints


def _days(dates: list[date]) -> Ints:
    return np.array(dates, dtype="datetime64[D]").astype(np.int64)


def series_columns(rows: npt.NDArray[np.void]) -> dict[str, npt.NDArray[np.generic]]:
    """The columns of a block of series rows, refusing a row whose fields have other widths."""
    widths = [rows[f"{name}_length"] == SERIES_ROW[name].itemsize for name in SERIES_FIELDS]
    if not (np.all(rows["field_count"] == len(SERIES_FIELDS)) and np.all(widths)):
        raise SeriesUnreadable("a continuous series row carries a field of an unexpected width")
    columns: dict[str, npt.NDArray[np.generic]] = {
        "isin": rows["isin"].copy(),
        "source_isin": rows["source_isin"].copy(),
        "is_nse": rows["venue"] == b"NSE",
        "day": rows["trade_date"].astype(np.int64) + POSTGRES_EPOCH_DAY,
        "as_of_day": rows["as_of_date"].astype(np.int64) + POSTGRES_EPOCH_DAY,
    }
    for measure in MEASURES:
        columns[measure] = rows[measure].astype(np.float64)
    return columns


def _cut(pending: bytearray) -> dict[str, npt.NDArray[np.generic]]:
    whole = len(pending) // SERIES_ROW.itemsize * SERIES_ROW.itemsize
    rows = np.frombuffer(bytes(pending[:whole]), dtype=SERIES_ROW)
    del pending[:whole]
    return series_columns(rows)


def read_continuous_series(connection: psycopg.Connection) -> ContinuousSeries:
    """Every bar of `int_continuous_prices`, in one pass."""
    parts = []
    pending = bytearray()
    header = False
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("select set_config('work_mem', %s, true)", (SERIES_SORT_MEMORY,))
        with cursor.copy(SERIES_COPY) as copy:
            for chunk in copy:
                pending += chunk
                if not header and len(pending) >= len(COPY_HEADER):
                    if pending[: len(COPY_HEADER)] != COPY_HEADER:
                        raise SeriesUnreadable("the stream does not open as a binary COPY")
                    del pending[: len(COPY_HEADER)]
                    header = True
                if header and len(pending) >= COPY_BLOCK_BYTES:
                    parts.append(_cut(pending))
    if not header or pending[-len(COPY_TRAILER) :] != COPY_TRAILER:
        raise SeriesUnreadable("the stream does not close as a binary COPY")
    del pending[-len(COPY_TRAILER) :]
    if len(pending) % SERIES_ROW.itemsize:
        raise SeriesUnreadable("the stream ends partway through a row")
    parts.append(_cut(pending))

    def joined(name: str) -> Any:
        return np.concatenate([part[name] for part in parts])

    return ContinuousSeries(
        isin=joined("isin"),
        source_isin=joined("source_isin"),
        is_nse=joined("is_nse"),
        day=joined("day"),
        as_of_day=joined("as_of_day"),
        close=joined("close"),
        high=joined("high"),
        low=joined("low"),
        volume=joined("volume"),
        delivery=joined("delivery"),
        turnover=joined("turnover"),
        adjustment_factor=joined("adjustment_factor"),
        close_as_traded=joined("close_as_traded"),
    )


def read_action_dates(connection: psycopg.Connection) -> ActionDates:
    """The ex-dates `int_capital_action_factors` applies a factor on."""
    rows = connection.execute(ACTIONS_QUERY).fetchall()
    return ActionDates(
        isin=np.array([row[0] for row in rows], dtype="S12"),
        ex_day=_days([row[1] for row in rows]),
        as_of_day=_days([row[2] for row in rows]),
    )


def read_verdicts(connection: psycopg.Connection) -> Verdicts:
    """The latest verdict on each venue's day, from `stg_trading_day`."""
    rows = connection.execute(VERDICTS_QUERY).fetchall()
    return Verdicts(
        is_nse=np.array([row[0] for row in rows], dtype=bool),
        day=_days([row[1] for row in rows]),
        is_complete=np.array([row[2] for row in rows], dtype=bool),
        as_of_day=_days([row[3] for row in rows]),
    )
