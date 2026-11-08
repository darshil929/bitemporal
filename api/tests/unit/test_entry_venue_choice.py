import pytest

from api.services.watchlist_management import ListedVenues, WatchlistRefused, chosen_venue

BOTH = ("BSE", "NSE")


@pytest.mark.parametrize(
    ("listed", "asked", "chosen"),
    [
        (ListedVenues(BOTH, "BSE"), None, "BSE"),
        (ListedVenues(BOTH, "BSE"), "NSE", "NSE"),
        (ListedVenues(BOTH, None), None, "NSE"),
        (ListedVenues(("BSE",), None), None, "BSE"),
        (ListedVenues(("BSE",), "NSE"), None, "BSE"),
    ],
)
def test_an_entry_follows_the_venue_asked_else_the_primary_else_nse_before_bse(
    listed: ListedVenues, asked: str | None, chosen: str
) -> None:
    assert chosen_venue(listed, asked) == chosen


@pytest.mark.parametrize(
    ("listed", "asked", "reason"),
    [
        (ListedVenues((), "NSE"), None, "instrument_not_listed"),
        (ListedVenues((), None), "BSE", "instrument_not_listed"),
        (ListedVenues(("BSE",), "BSE"), "NSE", "venue_not_listed"),
    ],
)
def test_an_entry_follows_only_a_venue_the_instrument_is_listed_on_now(
    listed: ListedVenues, asked: str | None, reason: str
) -> None:
    with pytest.raises(WatchlistRefused) as refused:
        chosen_venue(listed, asked)

    assert refused.value.reason == reason
