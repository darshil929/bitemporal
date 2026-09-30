"""The days a venue's day is measured against when its bars are counted."""

from datetime import date, timedelta

from pipelines.history import MINIMUM_NEIGHBOURS, NEIGHBOURS, usual_bars

FIRST_DAY = date(2022, 6, 1)


def days(*bars: int) -> list[tuple[date, int]]:
    return [(FIRST_DAY + timedelta(days=index), count) for index, count in enumerate(bars)]


def test_a_day_is_measured_against_the_days_before_it() -> None:
    """A sync judges a day before any later day is published."""
    counts = days(*[3454] * NEIGHBOURS, 2790, *[5000] * NEIGHBOURS)

    judged_day = counts[NEIGHBOURS][0]

    assert usual_bars(counts)[judged_day] == 3454


def test_the_days_before_are_the_nearest_twenty() -> None:
    counts = days(*[1000] * NEIGHBOURS, *[3000] * NEIGHBOURS, 2900)

    assert usual_bars(counts)[counts[-1][0]] == 3000


def test_the_first_days_of_a_history_are_measured_against_the_days_after() -> None:
    counts = days(1500, *[3000] * (NEIGHBOURS + 5))

    assert usual_bars(counts)[FIRST_DAY] == 3000


def test_a_history_too_short_to_compare_is_not_measured() -> None:
    counts = days(*[3000] * MINIMUM_NEIGHBOURS)

    assert usual_bars(counts) == {}
