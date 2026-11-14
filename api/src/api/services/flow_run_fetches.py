"""What a requested run has fetched in the window it runs: each daily file's answer by day, or by
year over a long window, and every failed fetch with its reason."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.flow_run_estimates import DAILY_SOURCES, RECENT

# Up to a month is shown day by day; a longer window, a bootstrap's, year by year.
DAY_BY_DAY = 31

REQUEST = text("select flow, first_day, last_day, started_at from flow_request where id = :id")
RUNS = text("select started_at, ended_at from flow_run where request_id = :id order by started_at")
ATTEMPTS = text(
    "select source_id, partition_key, outcome, detail from mart_fetch_attempts"
    " where fetched_at >= :since order by ingestion_id"
)


@dataclass(frozen=True)
class DayAnswers:
    day: date
    outcomes: dict[str, str]


@dataclass(frozen=True)
class YearAnswers:
    year: int
    days: int
    answered: dict[str, int]


@dataclass(frozen=True)
class FailedFetch:
    source: str
    key: str
    detail: str


@dataclass(frozen=True)
class Fetches:
    first_day: date
    last_day: date
    days: tuple[DayAnswers, ...] | None
    years: tuple[YearAnswers, ...] | None
    failures: tuple[FailedFetch, ...]


def windows_of(flow: str, first: date, last: date) -> list[tuple[date, date]]:
    """A sync's range; a bootstrap's two most recent years, then the days before them."""
    split = last - RECENT
    if flow == "sync" or split < first:
        return [(first, last)]
    return [(split + timedelta(days=1), last), (first, split)]


def by_year(
    first: date, last: date, answers: dict[tuple[str, date], str]
) -> tuple[YearAnswers, ...]:
    years = []
    for year in range(first.year, last.year + 1):
        start, end = max(first, date(year, 1, 1)), min(last, date(year, 12, 31))
        answered: dict[str, int] = defaultdict(int)
        for source, day in answers:
            if start <= day <= end:
                answered[source] += 1
        years.append(YearAnswers(year, (end - start).days + 1, dict(answered)))
    return tuple(years)


async def resolve_fetches(transaction: AsyncSession, request_id: int) -> Fetches | None:
    request = (await transaction.execute(REQUEST, {"id": request_id})).one_or_none()
    if request is None or request.started_at is None:
        return None
    runs = (await transaction.execute(RUNS, {"id": request_id})).all()
    windows = windows_of(request.flow, request.first_day, request.last_day)
    # The window running is the one after those recorded; once all are, the last.
    index = min(len(runs), len(windows) - 1)
    first, last = windows[index]
    since: datetime = request.started_at if index == 0 else runs[index - 1].ended_at
    answers: dict[tuple[str, date], str] = {}
    # Each slice's latest answer, so a fetch asked again and read is no longer a failure.
    latest: dict[tuple[str, str], tuple[str, str]] = {}
    for source, key, outcome, detail in await transaction.execute(ATTEMPTS, {"since": since}):
        latest[(source, key)] = (outcome, detail or "")
        if source in DAILY_SOURCES and len(key) == 10:
            day = date.fromisoformat(key)
            if first <= day <= last:
                answers[(source, day)] = outcome
    long_window = (last - first).days + 1 > DAY_BY_DAY
    days = None
    if not long_window:
        days = tuple(
            DayAnswers(
                first + timedelta(days=offset),
                {
                    source: outcome
                    for (source, day), outcome in answers.items()
                    if day == first + timedelta(days=offset)
                },
            )
            for offset in range((last - first).days + 1)
        )
    return Fetches(
        first,
        last,
        days,
        by_year(first, last, answers) if long_window else None,
        tuple(
            FailedFetch(source, key, detail)
            for (source, key), (outcome, detail) in latest.items()
            if outcome == "failed"
        ),
    )
