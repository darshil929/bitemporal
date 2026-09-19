"""Shared handling for the bhavcopy formats both venues have published."""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, BeforeValidator, ValidationError

from pipelines.models.market import PriceBar
from pipelines.sources.errors import MalformedRow

logger = logging.getLogger(__name__)

# Series that trade as ordinary equity. Every other series carries a bond, an exchange traded
# fund, a government security, a treasury bill, a warrant or a trust unit. A new equity series
# must be added here or its instruments are skipped.
EQUITY_SERIES: dict[str, frozenset[str]] = {
    "BSE": frozenset({"A", "B", "M", "MS", "MT", "P", "R", "T", "TS", "X", "XT", "Z", "ZP", "ZY"}),
    "NSE": frozenset({"EQ", "BE", "BZ", "SM", "ST"}),
}


def _blank_to_none(value: Any) -> Any:
    return None if isinstance(value, str) and not value.strip() else value


BlankAsNone = BeforeValidator(_blank_to_none)


class BhavcopyRow(BaseModel):
    """One row of any bhavcopy format, able to present itself as a canonical bar."""

    def to_bar(self, venue: str) -> PriceBar:
        raise NotImplementedError

    @property
    def series(self) -> str:
        raise NotImplementedError

    @property
    def security_name(self) -> str:
        """The instrument's name, falling back to its symbol where a format omits one."""
        raise NotImplementedError


def names_by_isin(rows: Sequence[BhavcopyRow], venue: str) -> dict[str, str]:
    """The name each equity row carries, keyed on ISIN.

    A venue names an instrument in every file it publishes, so the master takes its name from the
    day being read rather than from a separate source.
    """
    equity_series = EQUITY_SERIES[venue]
    return {
        row.to_bar(venue).isin: row.security_name for row in rows if row.series in equity_series
    }


def normalize(rows: Sequence[BhavcopyRow], venue: str) -> tuple[PriceBar, ...]:
    """Map the equity rows onto canonical bars, keyed on ISIN."""
    equity_series = EQUITY_SERIES[venue]
    skipped: Counter[str] = Counter()
    bars = []

    for row in rows:
        if row.series not in equity_series:
            skipped[row.series] += 1
            continue
        bars.append(row.to_bar(venue))

    if skipped:
        logger.info(
            "non-equity series skipped",
            extra={"venue": venue, "skipped": dict(skipped), "kept": len(bars)},
        )

    return tuple(bars)


# csv counts from the line after the header.
FIRST_DATA_LINE = 2

# A venue mangles a line at a time. A parser reading the wrong layout fails nearly every line,
# so the share of unreadable lines is what separates the two.
UNREADABLE_SHARE = 0.01


def validated[RowT: BhavcopyRow](
    model: type[RowT], rows: Iterable[Mapping[str, Any]], label: str
) -> tuple[RowT, ...]:
    """Read the rows that are bars, dropping the few a venue mangles.

    A venue occasionally publishes a line that is not a bar: BSE ran two records together on
    2022-02-07, truncating an ISIN across the join. Losing that day's other 3,931 bars over two
    broken lines costs more than it protects, so a line that cannot be read is logged and left
    out.

    Past a small share the file is being read wrongly rather than carrying a bad line, and the
    day is refused instead. Completeness does not cover this: it marks a day short only once it
    has lost half its bars.
    """
    parsed = []
    unreadable = []

    for number, row in enumerate(rows, start=FIRST_DATA_LINE):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError:
            unreadable.append(number)
            logger.warning(
                "bhavcopy line is not a bar",
                extra={
                    "source": label,
                    "line": number,
                    "begins": next(iter(row.values()), ""),
                },
            )

    if unreadable and len(unreadable) > UNREADABLE_SHARE * (len(parsed) + len(unreadable)):
        raise MalformedRow(
            f"{label} bhavcopy has {len(unreadable)} lines that are not bars"
            f" beside {len(parsed)} that are, first at line {unreadable[0]}"
        )

    return tuple(parsed)
