"""Deciding whether a venue's trading day may be read downstream."""

from datetime import date
from decimal import Decimal

from pipelines.models.market import PriceBar
from pipelines.validation import DIVERGENCE_LIMIT_BPS, divergences, validate_day

TRADE_DATE = date(2025, 6, 2)
RELIANCE = "INE002A01018"
INFOSYS = "INE009A01021"


# Well past the turnover two venues need before their prices are compared.
LIQUID = Decimal(100_000_000)


def bar(
    isin: str = RELIANCE,
    venue: str = "NSE",
    close: str = "100",
    day: date = TRADE_DATE,
    turnover: Decimal = LIQUID,
) -> PriceBar:
    return PriceBar(
        isin=isin,
        venue=venue,
        trade_date=day,
        as_of_date=day,
        local_symbol="X",
        scrip_code=None,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        previous_close=None,
        volume=1,
        turnover=turnover,
        trade_count=1,
    )


def many(count: int, venue: str = "NSE") -> list[PriceBar]:
    return [bar(isin=f"INE{index:09d}1", venue=venue) for index in range(count)]


def test_venues_that_agree_produce_no_divergence() -> None:
    assert divergences([bar(venue="BSE", close="100"), bar(venue="NSE", close="100")]) == {}


def test_a_gap_inside_tolerance_is_not_reported() -> None:
    """Ordinary spreads sit far below the limit; a quarter of a percent is unremarkable."""
    wide = divergences([bar(venue="BSE", close="100"), bar(venue="NSE", close="100.25")])

    assert wide == {}


def test_an_action_handled_at_one_venue_alone_is_reported() -> None:
    """A bonus applied at one venue halves its price and leaves the other where it was."""
    wide = divergences([bar(venue="BSE", close="100"), bar(venue="NSE", close="50")])

    assert set(wide) == {RELIANCE}
    assert wide[RELIANCE] > DIVERGENCE_LIMIT_BPS


def test_an_instrument_on_one_venue_alone_is_not_compared() -> None:
    assert divergences([bar(venue="BSE", close="100")]) == {}


def test_a_full_day_is_complete() -> None:
    verdict = validate_day("NSE", TRADE_DATE, many(150), typical_bars=150)

    assert verdict.is_complete
    assert verdict.detail is None
    assert verdict.bars == 150


def test_a_day_the_venue_published_nothing_for_is_incomplete() -> None:
    """A missing file must not read downstream as a flat price."""
    verdict = validate_day("NSE", TRADE_DATE, [])

    assert not verdict.is_complete
    assert "no bars" in (verdict.detail or "")


def test_a_truncated_file_is_incomplete() -> None:
    """Truncation is measured against what the venue usually lists, not a fixed count."""
    verdict = validate_day("NSE", TRADE_DATE, many(5), typical_bars=150)

    assert not verdict.is_complete
    assert "below" in (verdict.detail or "")


def test_a_smaller_universe_is_not_mistaken_for_truncation() -> None:
    verdict = validate_day("NSE", TRADE_DATE, many(35), typical_bars=35)

    assert verdict.is_complete


def test_a_bar_from_another_day_is_incomplete() -> None:
    bars = [*many(150), bar(isin=INFOSYS, day=date(2025, 6, 3))]

    verdict = validate_day("NSE", TRADE_DATE, bars, typical_bars=150)

    assert not verdict.is_complete
    assert "trade date" in (verdict.detail or "")


def test_a_divergent_instrument_makes_the_day_incomplete() -> None:
    bars = [*many(150), bar(venue="NSE", close="100")]
    other_venue = [bar(venue="BSE", close="50")]

    verdict = validate_day("NSE", TRADE_DATE, bars, other_venue, typical_bars=150)

    assert not verdict.is_complete
    assert verdict.divergent_instruments == 1
    assert "diverge" in (verdict.detail or "")


def test_a_verdict_is_knowable_on_the_day_it_describes() -> None:
    verdict = validate_day("NSE", TRADE_DATE, many(150), typical_bars=150)

    assert verdict.as_of_date == verdict.trade_date


def test_a_gap_on_a_thinly_traded_instrument_is_not_reported() -> None:
    """Sanwaria Consumer sat at 49 paise on BSE for months while NSE traded it at 19.

    A price pinned at a floor, or set by a single trade, cannot be held to another venue's.
    """
    thin = Decimal(100_000)
    pinned = [
        bar(venue="BSE", close="0.49", turnover=thin),
        bar(venue="NSE", close="0.19", turnover=thin),
    ]

    assert divergences(pinned) == {}


def test_a_gap_is_ignored_when_either_venue_traded_thinly() -> None:
    one_sided = [
        bar(venue="BSE", close="100", turnover=LIQUID),
        bar(venue="NSE", close="150", turnover=Decimal(1_000)),
    ]

    assert divergences(one_sided) == {}


def test_a_gap_where_both_venues_traded_heavily_is_reported() -> None:
    """Heavy trading at both venues holds the prices together, so a wide gap there is real."""
    both_liquid = [bar(venue="BSE", close="100"), bar(venue="NSE", close="150")]

    assert RELIANCE in divergences(both_liquid)


def test_a_gap_of_a_tick_or_two_on_a_low_priced_instrument_is_not_reported() -> None:
    """Reliance Power traded crores a day at under two rupees, where one step is several percent."""
    low_priced = [bar(venue="BSE", close="1.50"), bar(venue="NSE", close="1.60")]

    assert divergences(low_priced) == {}
