"""Shared handling for the bhavcopy formats both venues have published."""

import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, BeforeValidator, ValidationError

from pipelines.models.market import PriceBar
from pipelines.sources.errors import MalformedRow

logger = logging.getLogger(__name__)

# Series that trade as ordinary equity. BSE has also carried ordinary shares in XC, XD, ST and SS.
# NSE carries them in SZ, an SME series, and IT, its institutional trading platform. Exchange traded
# funds sit in BSE's E group and among NSE's EQ. Every other series carries a bond, a government
# security, a treasury bill, a warrant, a preference share, a partly paid share or a trust unit. A
# new equity series must be added here or its instruments are skipped.
EQUITY_SERIES: dict[str, frozenset[str]] = {
    "BSE": frozenset(
        {
            "A",
            "B",
            "E",
            "M",
            "MS",
            "MT",
            "P",
            "R",
            "SS",
            "ST",
            "T",
            "TS",
            "X",
            "XC",
            "XD",
            "XT",
            "Z",
            "ZP",
            "ZY",
        }
    ),
    "NSE": frozenset({"EQ", "BE", "BZ", "IT", "SM", "ST", "SZ"}),
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


# BSE numbers a second line for an ISIN by replacing the first digit of its ordinary scrip code: 1
# for a T+0 line and 6 for a deal window, whose prints can outweigh the ordinary line by value and
# by trades.
SECONDARY_LINE_CODE_PREFIXES = ("1", "6")


def ordinary_lines(bars: Iterable[PriceBar]) -> tuple[PriceBar, ...]:
    """The bar of each ISIN's ordinary line, one per ISIN, venue and day.

    One ISIN can trade on more than one line at a venue, each publishing a bar, and the ordinary
    line need not come first in the file. A line numbered as a second line gives way to any other,
    and among the rest the line with the most trades stands: a deal window under a code of its
    own, as BSE ran in 2023, trades a handful of times against hundreds on the ordinary line.
    """
    lines: dict[tuple[str, str, date], list[PriceBar]] = defaultdict(list)
    for bar in bars:
        lines[(bar.isin, bar.venue, bar.trade_date)].append(bar)
    return tuple(_ordinary_line(candidates) for candidates in lines.values())


def _ordinary_line(lines: Sequence[PriceBar]) -> PriceBar:
    candidates = [bar for bar in lines if not _numbered_as_second_line(bar)] or list(lines)
    return max(candidates, key=_trading_activity)


def _numbered_as_second_line(bar: PriceBar) -> bool:
    return bar.scrip_code is not None and bar.scrip_code.startswith(SECONDARY_LINE_CODE_PREFIXES)


def _trading_activity(bar: PriceBar) -> tuple[int, Decimal, int]:
    return bar.trade_count or 0, bar.turnover or Decimal(0), bar.volume


def _line(bar: PriceBar) -> tuple[str, str, date, str | None, str]:
    return bar.isin, bar.venue, bar.trade_date, bar.scrip_code, bar.local_symbol


def names_by_isin(rows: Sequence[BhavcopyRow], venue: str) -> dict[str, str]:
    """The name each ISIN's ordinary line carries.

    A venue names an instrument in every file it publishes, so the master takes its name from the
    day being read rather than from a separate source.
    """
    equity_series = EQUITY_SERIES[venue]
    named = [(row.to_bar(venue), row.security_name) for row in rows if row.series in equity_series]
    kept = {_line(bar) for bar in ordinary_lines(bar for bar, _ in named)}
    return {bar.isin: name for bar, name in named if _line(bar) in kept}


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

    A venue occasionally publishes a line that is not a bar, such as two records run together with
    an ISIN truncated across the join. Such a line is logged and left out, and the rest of the day
    stands. Past a small share the file is being read wrongly rather than carrying a bad line, and
    the day is refused instead. Completeness does not cover this: a few lost lines leave a day well
    above the share of its usual count that marks it short.
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
