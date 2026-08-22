"""Builds the committed fixture dataset from real bhavcopies.

Runs in three passes. `download` pulls every trading day in the range into the source cache.
`survey` streams the cache and records, per instrument and venue, the facts the selection needs.
`select` picks instruments until every required edge case is present and writes the seed files.

The download hits both exchanges and is rate limited, so it takes hours on a cold cache and
minutes on a warm one. Nothing here runs in CI.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

import httpx

from pipelines.config.settings import SourceSettings
from pipelines.identity import derive_listings, venue_key
from pipelines.models.corporate_action import CorporateActionRecord
from pipelines.models.identity import ListingRecord
from pipelines.models.market import DeliveryRecord, PriceBar
from pipelines.sources.bhavcopy import EQUITY_SERIES
from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.bse.corporate_actions import BseCorporateActions
from pipelines.sources.bse.delivery import BseDelivery
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.errors import NotPublished, SourceError
from pipelines.sources.nse.bhavcopy import NseBhavcopy
from pipelines.sources.nse.delivery import NseDelivery
from pipelines.sources.registry import SourceDefinition, load_definitions
from pipelines.validation import DayVerdict, validate_day

logger = logging.getLogger("fixture")

SEED_DIR = Path("pipelines/tests/fixtures/seed")
SURVEY_FILE = Path("survey.json")

PRICE_COLUMNS = [
    "isin",
    "venue",
    "trade_date",
    "as_of_date",
    "open",
    "high",
    "low",
    "close",
    "previous_close",
    "volume",
    "turnover",
    "trade_count",
]

# A split or a bonus shows as an unexplained fall against the previous close the venue itself
# published on the row.
ACTION_RATIO = Decimal("0.7")

UDIFF = "udiff"

ACTIONS_BASE_URL = "https://api.bseindia.com/BseIndiaAPI/api"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


@dataclass
class Track:
    """What one instrument did at one venue over the range."""

    first_day: date | None = None
    last_day: date | None = None
    days: int = 0
    symbols: set[str] = field(default_factory=set)
    turnover: Decimal = Decimal(0)
    worst_ratio: Decimal | None = None
    worst_ratio_day: date | None = None
    longest_gap: int = 0
    _previous_day: date | None = None

    def observe(self, bar: PriceBar, trading_days: list[date]) -> None:
        if self.first_day is None:
            self.first_day = bar.trade_date
        self.last_day = bar.trade_date
        self.days += 1
        self.symbols.add(bar.local_symbol)
        self.turnover += bar.turnover or Decimal(0)

        if self._previous_day is not None:
            gap = _trading_days_between(trading_days, self._previous_day, bar.trade_date)
            self.longest_gap = max(self.longest_gap, gap)
        self._previous_day = bar.trade_date

        if bar.previous_close and bar.previous_close > 0:
            ratio = bar.close / bar.previous_close
            if self.worst_ratio is None or ratio < self.worst_ratio:
                self.worst_ratio = ratio
                self.worst_ratio_day = bar.trade_date


def _trading_days_between(trading_days: list[date], start: date, end: date) -> int:
    return sum(1 for day in trading_days if start < day < end)


def _adapters(cache: DiskCache) -> dict[str, tuple[object, SourceDefinition]]:
    definitions = {item.source_id: item for item in load_definitions()}
    plain = httpx.Client(
        headers={"User-Agent": SourceSettings().source_user_agent}, follow_redirects=True
    )
    browser = httpx.Client(
        headers={"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
    )

    bse_definition = definitions["bse_bhavcopy_equity"]
    nse_definition = definitions["nse_bhavcopy_equity"]

    return {
        "BSE": (
            BseBhavcopy(
                ThrottledClient(
                    bse_definition.source_id,
                    plain,
                    Throttle(1 / bse_definition.requests_per_second),
                ),
                cache,
                bse_definition.base_url,
            ),
            bse_definition,
        ),
        "NSE": (
            NseBhavcopy(
                ThrottledClient(
                    nse_definition.source_id,
                    browser,
                    Throttle(1 / nse_definition.requests_per_second),
                ),
                cache,
                nse_definition.base_url,
            ),
            nse_definition,
        ),
    }


def _weekdays(start: date, end: date) -> list[date]:
    days, current = [], start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def read_day(adapter: object, definition: SourceDefinition, day: date) -> tuple[PriceBar, ...]:
    version = definition.version_for(day)
    payload = adapter.fetch(day, version)  # type: ignore[attr-defined]
    rows = adapter.parse(payload, version)  # type: ignore[attr-defined]
    return tuple(adapter.normalize(rows))  # type: ignore[attr-defined]


def download(start: date, end: date, cache: DiskCache) -> None:
    adapters = _adapters(cache)
    for venue, (adapter, definition) in adapters.items():
        published = missing = failed = 0
        for day in _weekdays(start, end):
            try:
                read_day(adapter, definition, day)
                published += 1
            except NotPublished:
                missing += 1
            except SourceError:
                failed += 1
                logger.warning("day unavailable", extra={"venue": venue, "day": day.isoformat()})
        logger.info(
            "download complete",
            extra={"venue": venue, "published": published, "missing": missing, "failed": failed},
        )


def survey(start: date, end: date, cache: DiskCache) -> dict[str, dict[str, Track]]:
    adapters = _adapters(cache)
    tracks: dict[str, dict[str, Track]] = defaultdict(dict)

    for venue, (adapter, definition) in adapters.items():
        trading_days = []
        days_bars: list[tuple[date, tuple[PriceBar, ...]]] = []
        for day in _weekdays(start, end):
            try:
                bars = read_day(adapter, definition, day)
            except SourceError:
                continue
            trading_days.append(day)
            days_bars.append((day, bars))

        for _, bars in days_bars:
            for bar in bars:
                track = tracks[bar.isin].setdefault(venue, Track())
                track.observe(bar, trading_days)

        logger.info("survey complete", extra={"venue": venue, "trading_days": len(trading_days)})

    return tracks


class VenueSurvey(TypedDict):
    first_day: str | None
    last_day: str | None
    days: int
    symbols: list[str]
    turnover: str
    worst_ratio: str | None
    worst_ratio_day: str | None
    longest_gap: int


Entry = dict[str, VenueSurvey]


@dataclass
class Requirement:
    """One property the committed dataset must exhibit, and how to spot it."""

    name: str
    holds: Callable[[Entry], bool]
    wanted: int = 1


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _requirements(range_end: date) -> list[Requirement]:
    settled = range_end - timedelta(days=90)
    recent = range_end - timedelta(days=60)
    late = range_end - timedelta(days=400)

    def had_a_capital_action(entry: Entry) -> bool:
        return any(
            venue["worst_ratio"] is not None and Decimal(venue["worst_ratio"]) < ACTION_RATIO
            for venue in entry.values()
        )

    def changed_symbol(entry: Entry) -> bool:
        # Only NSE names an instrument by ticker across the whole window, so only NSE can show
        # a rename rather than a change in how the file identifies instruments.
        nse = entry.get("NSE")
        return nse is not None and len(nse["symbols"]) > 1

    def stopped_trading(entry: Entry) -> bool:
        ends = [_day(venue["last_day"]) for venue in entry.values()]
        return bool(ends) and all(end is not None and end < settled for end in ends)

    def paused_and_resumed(entry: Entry) -> bool:
        return any(
            venue["longest_gap"] >= 15 and (_day(venue["last_day"]) or date.min) > recent
            for venue in entry.values()
        )

    def listed_only_on_bse(entry: Entry) -> bool:
        return set(entry) == {"BSE"}

    def listed_on_both(entry: Entry) -> bool:
        return set(entry) == {"BSE", "NSE"}

    def started_late(entry: Entry) -> bool:
        starts = [_day(venue["first_day"]) for venue in entry.values()]
        return bool(starts) and all(start is not None and start > late for start in starts)

    return [
        Requirement("capital_action", had_a_capital_action, 2),
        Requirement("symbol_change", changed_symbol),
        Requirement("delisted", stopped_trading),
        Requirement("suspended", paused_and_resumed),
        Requirement("bse_only", listed_only_on_bse, 3),
        Requirement("short_history", started_late, 2),
        Requirement("dual_listed", listed_on_both, 25),
    ]


def choose(survey_data: dict[str, Entry], range_end: date) -> dict[str, str]:
    """Pick instruments until every requirement is met, preferring the most traded."""

    def liquidity(isin: str) -> Decimal:
        return sum((Decimal(venue["turnover"]) for venue in survey_data[isin].values()), Decimal(0))

    ranked = sorted(survey_data, key=liquidity, reverse=True)
    chosen: dict[str, str] = {}

    for requirement in _requirements(range_end):
        found = 0
        for isin in ranked:
            if found >= requirement.wanted:
                break
            if isin in chosen:
                continue
            if requirement.holds(survey_data[isin]):
                chosen[isin] = requirement.name
                found += 1
        if found < requirement.wanted:
            logger.warning(
                "requirement under-filled",
                extra={
                    "requirement": requirement.name,
                    "found": found,
                    "wanted": requirement.wanted,
                },
            )

    return chosen


def emit(
    chosen: dict[str, str], start: date, end: date, cache: DiskCache, seed_dir: Path
) -> dict[str, int]:
    """Write the seed files, holding only the chosen instruments.

    A venue can carry one instrument on more than one security line, BSE's T+0 segment beside the
    ordinary one. Both would claim the same bar, so only the line that traded the most value over
    the window is kept.
    """
    adapters = _adapters(cache)
    seed_dir.mkdir(parents=True, exist_ok=True)

    names: dict[str, str] = {}
    traded: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    collected: dict[tuple[str, str, str], list[PriceBar]] = defaultdict(list)
    last_trading_day: dict[str, date] = {}

    for venue, (adapter, definition) in adapters.items():
        for day in _weekdays(start, end):
            try:
                version = definition.version_for(day)
                payload = adapter.fetch(day, version)  # type: ignore[attr-defined]
                rows = adapter.parse(payload, version)  # type: ignore[attr-defined]
            except SourceError:
                continue

            last_trading_day[venue] = day
            for row in rows:
                if row.isin not in chosen or row.series not in EQUITY_SERIES[venue]:
                    continue
                bar = row.to_bar(venue)
                if version == UDIFF or bar.isin not in names:
                    names[bar.isin] = row.security_name
                key = (bar.isin, venue, venue_key(bar))
                traded[key] += bar.turnover or Decimal(0)
                collected[key].append(bar)

    dominant = _dominant_lines(traded)
    written = _write_prices(seed_dir, collected, dominant)
    kept = [bar for key in dominant for bar in collected[key]]

    listings = derive_listings(kept, last_trading_day)
    actions = collect_actions(listings, cache, end)

    _write_instruments(seed_dir, chosen, names)
    _write_listings(seed_dir, listings)
    _write_actions(seed_dir, actions)
    return {
        "instruments": len(chosen),
        "price_rows": written,
        "lines": len(dominant),
        "actions": len(actions),
    }


def collect_actions(
    listings: Sequence[ListingRecord], cache: DiskCache, reported_on: date
) -> tuple[CorporateActionRecord, ...]:
    """Read the action history of every BSE scrip in the dataset."""
    settings = SourceSettings()
    client = httpx.Client(
        headers={"User-Agent": settings.source_user_agent},
        follow_redirects=True,
    )
    adapter = BseCorporateActions(
        ThrottledClient("bse_corporate_actions", client, Throttle(2.0)), cache, ACTIONS_BASE_URL
    )

    isin_for_scrip = {
        listing.scrip_code: listing.isin
        for listing in listings
        if listing.exchange == "BSE" and listing.scrip_code
    }

    actions: list[CorporateActionRecord] = []
    for scrip_code in sorted(isin_for_scrip):
        try:
            payload = adapter.fetch(scrip_code)
        except SourceError:
            logger.warning("actions unavailable", extra={"scrip_code": scrip_code})
            continue
        actions.extend(adapter.normalize(adapter.parse(payload), isin_for_scrip, reported_on))

    return tuple(actions)


def _write_actions(seed_dir: Path, actions: Sequence[CorporateActionRecord]) -> None:
    ordered = sorted(
        actions, key=lambda item: (item.isin, item.ex_date, item.action_type, item.qualifier)
    )
    with (seed_dir / "corporate_action.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "isin",
                "action_type",
                "ex_date",
                "source_id",
                "as_of_date",
                "qualifier",
                "ratio_from",
                "ratio_to",
                "dividend_amount",
            ]
        )
        for item in ordered:
            writer.writerow(
                [
                    item.isin,
                    item.action_type,
                    item.ex_date.isoformat(),
                    item.source_id,
                    item.as_of_date.isoformat(),
                    item.qualifier,
                    "" if item.ratio_from is None else str(item.ratio_from),
                    "" if item.ratio_to is None else str(item.ratio_to),
                    "" if item.dividend_amount is None else str(item.dividend_amount),
                ]
            )


def collect_delivery(start: date, end: date, cache: DiskCache) -> tuple[DeliveryRecord, ...]:
    """Read the delivery figure for every trading day in the range, at both venues.

    Neither file names an instrument by ISIN, so each is resolved through the listing that the
    dataset already records for the venue-local identifier it carries.
    """
    listings = _committed_listings()
    settings = SourceSettings()
    plain = httpx.Client(headers={"User-Agent": settings.source_user_agent}, follow_redirects=True)
    browser = httpx.Client(
        headers={"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
    )

    adapters: dict[str, tuple[BseDelivery | NseDelivery, dict[str, str]]] = {
        "BSE": (
            BseDelivery(
                ThrottledClient("bse_delivery", plain, Throttle(2.0)),
                cache,
                "https://www.bseindia.com/BSEDATA/gross",
            ),
            {key: isin for (venue, key), isin in listings.items() if venue == "BSE"},
        ),
        "NSE": (
            NseDelivery(
                ThrottledClient("nse_delivery", browser, Throttle(2.0)),
                cache,
                "https://nsearchives.nseindia.com",
            ),
            {key: isin for (venue, key), isin in listings.items() if venue == "NSE"},
        ),
    }

    records: list[DeliveryRecord] = []
    for venue, (adapter, resolver) in adapters.items():
        published = missing = 0
        for day in _weekdays(start, end):
            try:
                payload = adapter.fetch(day)
            except NotPublished:
                missing += 1
                continue
            except SourceError:
                logger.warning("delivery unavailable", extra={"venue": venue, "day": day})
                continue
            published += 1
            records.extend(adapter.normalize(adapter.parse(payload), resolver))
        logger.info(
            "delivery collected",
            extra={"venue": venue, "published": published, "missing": missing},
        )

    return tuple(records)


def _committed_listings() -> dict[tuple[str, str], str]:
    """Map each venue-local identifier in the dataset to the ISIN it belongs to."""
    resolver: dict[tuple[str, str], str] = {}
    with (SEED_DIR / "listing.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = row["scrip_code"] or row["local_symbol"]
            resolver[(row["exchange"], key)] = row["isin"]
    return resolver


def _write_delivery(seed_dir: Path, records: Sequence[DeliveryRecord]) -> int:
    seen: set[tuple[str, str, date]] = set()
    ordered = sorted(records, key=lambda item: (item.isin, item.venue, item.trade_date))
    with (seed_dir / "delivery_daily.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["isin", "venue", "trade_date", "as_of_date", "delivery_quantity"])
        written = 0
        for item in ordered:
            key = (item.isin, item.venue, item.trade_date)
            if key in seen:
                continue
            seen.add(key)
            writer.writerow(
                [
                    item.isin,
                    item.venue,
                    item.trade_date.isoformat(),
                    item.as_of_date.isoformat(),
                    item.delivery_quantity,
                ]
            )
            written += 1
    return written


def validate_committed_days() -> tuple[DayVerdict, ...]:
    """Reach a verdict on every venue day the committed dataset holds."""
    by_day: dict[tuple[str, date], list[PriceBar]] = defaultdict(list)
    with (SEED_DIR / "price_daily.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            bar = PriceBar(
                isin=row["isin"],
                venue=row["venue"],
                trade_date=date.fromisoformat(row["trade_date"]),
                as_of_date=date.fromisoformat(row["as_of_date"]),
                local_symbol="",
                scrip_code=None,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                previous_close=Decimal(row["previous_close"]) if row["previous_close"] else None,
                volume=int(row["volume"]),
                turnover=Decimal(row["turnover"]) if row["turnover"] else None,
                trade_count=int(row["trade_count"]) if row["trade_count"] else None,
            )
            by_day[(bar.venue, bar.trade_date)].append(bar)

    counts: dict[str, list[int]] = defaultdict(list)
    for (venue, _), bars in by_day.items():
        counts[venue].append(len(bars))
    typical = {venue: sorted(values)[len(values) // 2] for venue, values in counts.items()}

    verdicts = []
    for (venue, day), bars in sorted(by_day.items()):
        other = [b for v, d in by_day if v != venue and d == day for b in by_day[(v, d)]]
        verdicts.append(validate_day(venue, day, bars, other, typical_bars=typical[venue]))
    return tuple(verdicts)


def _write_trading_days(seed_dir: Path, verdicts: Sequence[DayVerdict]) -> None:
    with (seed_dir / "trading_day.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "venue",
                "trade_date",
                "as_of_date",
                "is_complete",
                "bars",
                "divergent_instruments",
                "detail",
            ]
        )
        for verdict in verdicts:
            writer.writerow(
                [
                    verdict.venue,
                    verdict.trade_date.isoformat(),
                    verdict.as_of_date.isoformat(),
                    "true" if verdict.is_complete else "false",
                    verdict.bars,
                    verdict.divergent_instruments,
                    verdict.detail or "",
                ]
            )


def _dominant_lines(traded: dict[tuple[str, str, str], Decimal]) -> set[tuple[str, str, str]]:
    best: dict[tuple[str, str], tuple[Decimal, str]] = {}
    for (isin, venue, line), turnover in traded.items():
        current = best.get((isin, venue))
        if current is None or turnover > current[0]:
            best[(isin, venue)] = (turnover, line)
    return {(isin, venue, line) for (isin, venue), (_, line) in best.items()}


def _write_prices(
    seed_dir: Path,
    collected: dict[tuple[str, str, str], list[PriceBar]],
    dominant: set[tuple[str, str, str]],
) -> int:
    written = 0
    with (seed_dir / "price_daily.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(PRICE_COLUMNS)
        for key in sorted(dominant):
            for bar in sorted(collected[key], key=lambda item: item.trade_date):
                writer.writerow(_price_row(bar))
                written += 1
    return written


def _price_row(bar: PriceBar) -> list[str]:
    return [
        bar.isin,
        bar.venue,
        bar.trade_date.isoformat(),
        bar.as_of_date.isoformat(),
        str(bar.open),
        str(bar.high),
        str(bar.low),
        str(bar.close),
        "" if bar.previous_close is None else str(bar.previous_close),
        str(bar.volume),
        "" if bar.turnover is None else str(bar.turnover),
        "" if bar.trade_count is None else str(bar.trade_count),
    ]


def _write_instruments(seed_dir: Path, chosen: dict[str, str], names: dict[str, str]) -> None:
    with (seed_dir / "instrument_master.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["isin", "name", "sector", "country", "instrument_type"])
        for isin in sorted(chosen):
            writer.writerow([isin, names.get(isin, isin), "", "IN", "equity"])


def _write_listings(seed_dir: Path, listings: Sequence[ListingRecord]) -> None:
    with (seed_dir / "listing.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "isin",
                "exchange",
                "local_symbol",
                "scrip_code",
                "listing_date",
                "delisting_date",
                "closure_reason",
            ]
        )
        for listing in listings:
            writer.writerow(
                [
                    listing.isin,
                    listing.exchange,
                    listing.local_symbol,
                    listing.scrip_code or "",
                    listing.listing_date.isoformat(),
                    listing.delisting_date.isoformat() if listing.delisting_date else "",
                    listing.closure_reason or "",
                ]
            )


def _serialise(tracks: dict[str, dict[str, Track]]) -> dict[str, Entry]:
    return {
        isin: {
            venue: {
                "first_day": track.first_day.isoformat() if track.first_day else None,
                "last_day": track.last_day.isoformat() if track.last_day else None,
                "days": track.days,
                "symbols": sorted(track.symbols),
                "turnover": str(track.turnover),
                "worst_ratio": str(track.worst_ratio) if track.worst_ratio else None,
                "worst_ratio_day": (
                    track.worst_ratio_day.isoformat() if track.worst_ratio_day else None
                ),
                "longest_gap": track.longest_gap,
            }
            for venue, track in venues.items()
        }
        for isin, venues in tracks.items()
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["download", "survey", "emit", "delivery", "validate"])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--survey-file", type=Path, default=SURVEY_FILE)
    arguments = parser.parse_args()

    cache = DiskCache(SourceSettings().source_cache_dir)

    if arguments.stage == "download":
        download(arguments.start, arguments.end, cache)
        return 0

    if arguments.stage == "survey":
        tracks = survey(arguments.start, arguments.end, cache)
        arguments.survey_file.write_text(
            json.dumps(_serialise(tracks), indent=1, sort_keys=True), encoding="utf-8"
        )
        logger.info("survey written", extra={"instruments": len(tracks)})
        return 0

    if arguments.stage == "validate":
        verdicts = validate_committed_days()
        _write_trading_days(SEED_DIR, verdicts)
        incomplete = sum(1 for item in verdicts if not item.is_complete)
        logger.info("verdicts written", extra={"days": len(verdicts), "incomplete": incomplete})
        return 0

    if arguments.stage == "delivery":
        records = collect_delivery(arguments.start, arguments.end, cache)
        written = _write_delivery(SEED_DIR, records)
        logger.info("delivery written", extra={"rows": written})
        return 0

    survey_data = json.loads(arguments.survey_file.read_text(encoding="utf-8"))
    chosen = choose(survey_data, arguments.end)
    counts = emit(chosen, arguments.start, arguments.end, cache, SEED_DIR)
    logger.info("seed written", extra=counts)
    for requirement, isin in sorted((value, key) for key, value in chosen.items()):
        logger.info("chosen %s %s", requirement, isin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
