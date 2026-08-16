"""Shared handling for the bhavcopy formats both venues have published."""

import logging
from collections import Counter
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, BeforeValidator

from pipelines.models.market import PriceBar

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
