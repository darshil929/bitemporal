"""Validation that decides whether a venue's trading day may be read downstream.

A day is complete only once it passes every check here. A missing bhavcopy that silently produced
no rows would otherwise read downstream as a flat price rather than as an absence.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from pipelines.models.market import PriceBar

logger = logging.getLogger(__name__)

# Observed spreads on the committed dataset sit under 25 basis points at the ninety ninth
# percentile and peak at 175 on a suspended instrument. An action handled at one venue and not the
# other moves a price by half, which is five thousand.
DIVERGENCE_LIMIT_BPS = Decimal(500)

# A file that arrives truncated carries a fraction of the instruments the venue usually lists,
# so the floor is relative to that rather than a count no subset of the market would meet.
TRUNCATION_FRACTION = Decimal("0.5")

BASIS_POINTS = Decimal(10000)


@dataclass(frozen=True)
class DayVerdict:
    """The outcome of validating one venue's day."""

    venue: str
    trade_date: date
    as_of_date: date
    is_complete: bool
    bars: int
    divergent_instruments: int
    detail: str | None


def divergences(
    bars: Sequence[PriceBar], limit_bps: Decimal = DIVERGENCE_LIMIT_BPS
) -> dict[str, Decimal]:
    """Instruments whose two venue closes disagree beyond tolerance, in basis points.

    Blending the venues is forbidden, so the two series are only ever compared. A gap this wide
    almost always means a corporate action handled at one venue and not the other.
    """
    closes: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for bar in bars:
        closes[bar.isin][bar.venue] = bar.close

    wide = {}
    for isin, venues in closes.items():
        if len(venues) < 2:
            continue
        values = list(venues.values())
        midpoint = sum(values, Decimal(0)) / len(values)
        if midpoint <= 0:
            continue
        spread = (max(values) - min(values)) / midpoint * BASIS_POINTS
        if spread > limit_bps:
            wide[isin] = spread

    return wide


def validate_day(
    venue: str,
    trade_date: date,
    bars: Sequence[PriceBar],
    cross_venue_bars: Sequence[PriceBar] = (),
    typical_bars: int | None = None,
) -> DayVerdict:
    """Decide whether one venue's day may be read downstream.

    `typical_bars` is how many the venue usually publishes, against which a truncated file is
    recognised. Left out, only an empty day fails on count.
    """
    failures = []
    floor = int(TRUNCATION_FRACTION * typical_bars) if typical_bars else 0

    if not bars:
        failures.append("the venue published no bars")
    elif len(bars) < floor:
        failures.append(f"only {len(bars)} bars, below the {floor} a full file carries")

    if any(bar.trade_date != trade_date for bar in bars):
        failures.append("a bar carries a trade date other than the day it was read for")

    wide = divergences([*bars, *cross_venue_bars])
    if wide:
        worst = max(wide.values())
        failures.append(
            f"{len(wide)} instruments diverge across venues, worst {worst:.0f} basis points"
        )

    verdict = DayVerdict(
        venue=venue,
        trade_date=trade_date,
        as_of_date=trade_date,
        is_complete=not failures,
        bars=len(bars),
        divergent_instruments=len(wide),
        detail="; ".join(failures) or None,
    )

    if failures:
        logger.warning(
            "trading day incomplete",
            extra={"venue": venue, "trade_date": trade_date.isoformat(), "detail": verdict.detail},
        )

    return verdict


def persist_verdicts(connection: psycopg.Connection, verdicts: Sequence[DayVerdict]) -> None:
    """Record each verdict, leaving one already written for the same as-of date in place."""
    for verdict in verdicts:
        connection.execute(
            "insert into trading_day"
            " (venue, trade_date, as_of_date, is_complete, bars, divergent_instruments, detail)"
            " values (%s, %s, %s, %s, %s, %s, %s)"
            " on conflict (venue, trade_date, as_of_date) do nothing",
            (
                verdict.venue,
                verdict.trade_date,
                verdict.as_of_date,
                verdict.is_complete,
                verdict.bars,
                verdict.divergent_instruments,
                verdict.detail,
            ),
        )

    incomplete = sum(1 for verdict in verdicts if not verdict.is_complete)
    logger.info("trading days recorded", extra={"days": len(verdicts), "incomplete": incomplete})
