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


def validated[RowT: BhavcopyRow](
    model: type[RowT], rows: Iterable[Mapping[str, Any]], label: str
) -> tuple[RowT, ...]:
    """Read every row as a bar, naming the line a malformed file fails on.

    A venue occasionally publishes a line that is not a bar: BSE ran two records together on
    2022-02-07, truncating an ISIN. Pydantic reports that as a validation error, which says
    nothing about which file or line it came from and is not a source failure any caller
    recognises.
    """
    parsed = []
    for number, row in enumerate(rows, start=FIRST_DATA_LINE):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as error:
            first = next(iter(row.values()), "")
            raise MalformedRow(
                f"{label} bhavcopy line {number} is not a bar, beginning {first!r}"
            ) from error
    return tuple(parsed)
