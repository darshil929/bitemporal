"""Ranges of ex-dates, as both venues' corporate action endpoints are asked for them."""

from datetime import date

# An action is announced ahead of its ex-date, which can fall in the following year.
YEARS_AHEAD = 1


def calendar_years(first_year: int, collected_on: date) -> list[tuple[date, date]]:
    """Every calendar year of ex-dates from the first a venue records to the one after collection."""
    return [
        (date(year, 1, 1), date(year, 12, 31))
        for year in range(first_year, collected_on.year + YEARS_AHEAD + 1)
    ]


def range_key(first: date, last: date, collected_on: date) -> str:
    """The cache key for one range of ex-dates.

    An answer for a range still open on the collection day changes as actions are announced, so
    it is held under that day rather than for good.
    """
    key = f"exdate-{first:%Y%m%d}-{last:%Y%m%d}"
    if last >= collected_on:
        key += f"-as-of-{collected_on:%Y%m%d}"
    return key
