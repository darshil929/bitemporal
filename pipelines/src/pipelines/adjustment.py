"""Adjustment of published prices for actions that changed the share count."""

import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.models.market import PriceBar

logger = logging.getLogger(__name__)

# A dividend reduces the price on its ex-date but leaves the share count alone. Adjusting for one
# produces a total return series, which is a different thing from a price series, so the price
# series carries share count actions only.
COUNT_CHANGING = frozenset({"split", "bonus", "consolidation"})

PRICE_PLACES = Decimal("0.0001")


def factor_schedule(
    actions: Sequence[CorporateActionRecord],
) -> dict[str, tuple[tuple[date, Decimal], ...]]:
    """The factor applying to bars before each ex-date, per instrument.

    Rebuilt from the whole history every time rather than carried forward, so an action added
    later corrects every earlier bar instead of leaving a step in the series.
    """
    by_instrument: dict[str, list[CorporateActionRecord]] = defaultdict(list)
    for action in actions:
        if action.action_type in COUNT_CHANGING and action.ratio_from and action.ratio_to:
            by_instrument[action.isin].append(action)

    schedule: dict[str, tuple[tuple[date, Decimal], ...]] = {}
    for isin, relevant in by_instrument.items():
        latest = _latest_by_ex_date(relevant)
        running = Decimal(1)
        steps: list[tuple[date, Decimal]] = []
        for action in sorted(latest, key=lambda item: item.ex_date, reverse=True):
            running *= Decimal(action.ratio_from) / Decimal(action.ratio_to)  # type: ignore[arg-type]
            steps.append((action.ex_date, running))
        schedule[isin] = tuple(reversed(steps))

    return schedule


def _latest_by_ex_date(actions: Sequence[CorporateActionRecord]) -> list[CorporateActionRecord]:
    """Keep the most recently reported version of each action."""
    newest: dict[tuple[str, date], CorporateActionRecord] = {}
    for action in actions:
        key = (action.action_type, action.ex_date)
        held = newest.get(key)
        if held is None or action.as_of_date > held.as_of_date:
            newest[key] = action
    return list(newest.values())


def factor_for(schedule: tuple[tuple[date, Decimal], ...], trade_date: date) -> Decimal:
    """The factor for a bar, which is the product of every action still ahead of it."""
    for ex_date, factor in schedule:
        if trade_date < ex_date:
            return factor
    return Decimal(1)


def adjusted_close(bar: PriceBar, schedule: dict[str, tuple[tuple[date, Decimal], ...]]) -> Decimal:
    return _scale(bar.close, factor_for(schedule.get(bar.isin, ()), bar.trade_date))


def adjust(
    bars: Sequence[PriceBar], actions: Sequence[CorporateActionRecord]
) -> dict[tuple[str, str, date], Decimal]:
    """Return the adjusted close for every bar, keyed on instrument, venue and trade date."""
    schedule = factor_schedule(actions)
    adjusted = {
        (bar.isin, bar.venue, bar.trade_date): adjusted_close(bar, schedule) for bar in bars
    }

    logger.info(
        "prices adjusted",
        extra={"bars": len(adjusted), "instruments_with_actions": len(schedule)},
    )
    return adjusted


def _scale(price: Decimal, factor: Decimal) -> Decimal:
    return (price * factor).quantize(PRICE_PLACES)
